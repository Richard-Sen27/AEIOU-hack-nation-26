"""Account: session info, settings, consents, patient profile, data export, deletion."""

import json
import logging
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Response
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.api.services.contributions import contribution_from_row, refresh_shared_graph
from backend.config import get_settings
from backend.schemas.account import (
    AccountInfo,
    ChatSessionExport,
    Consent,
    ConsentGrant,
    CurrentUser,
    DataExport,
    OpenAIConnection,
    ProfileSettings,
    SessionInfo,
    SessionUser,
    SettingsUpdate,
)
from backend.schemas.chat import AgentReply, ChatMessage, ChatSession
from backend.schemas.contributions import EdgeFlag
from backend.schemas.documents import Document, Finding, Job
from backend.schemas.enums import ConsentType, ErrorCode, ProfileSource, Role
from backend.schemas.profile import (
    PatientProfile,
    ProfileDisease,
    ProfileGene,
    ProfilePhenotype,
    ProfileVariant,
)

log = logging.getLogger(__name__)

ProfileItemModel = ProfileDisease | ProfileGene | ProfileVariant | ProfilePhenotype

_SESSION_USER_SQL = text(
    """
    SELECT u.id, u.name, u.email, p.role, p.role_verified, p.language, p.expert_mode,
           p.gpc_opt_out, p.age_confirmed_at IS NOT NULL AS age_confirmed,
           COALESCE(
             (SELECT array_agg(DISTINCT c.consent_type ORDER BY c.consent_type) FROM consents c
               WHERE c.user_id = u.id AND c.revoked_at IS NULL),
             '{}'
           ) AS consents
      FROM users u JOIN profiles p ON p.user_id = u.id
     WHERE u.id = :uid
    """
)


async def current_data_version(db: AsyncSession) -> str | None:
    from backend.api.services.graph import get_graph

    version = get_graph().data_version
    if version:
        return version
    return await db.scalar(
        text("SELECT data_version FROM ingestion_runs ORDER BY created_at DESC LIMIT 1")
    )


async def session_user(db: AsyncSession, user_id: UUID) -> SessionUser:
    row = (await db.execute(_SESSION_USER_SQL, {"uid": user_id})).mappings().first()
    if row is None:
        raise ApiError(401, ErrorCode.sign_in_required)
    return SessionUser(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        role=Role(row["role"]) if row["role"] else None,
        role_verified=row["role_verified"],
        language=row["language"] or "en",
        expert_mode=row["expert_mode"],
        age_confirmed=row["age_confirmed"],
        consents=[ConsentType(c) for c in row["consents"]],
        gpc_opt_out=row["gpc_opt_out"],
    )


async def get_session_info(db: AsyncSession, user: CurrentUser | None, gpc: bool) -> SessionInfo:
    """Who is signed in (or null), GPC signal, demo mode and data version."""
    return SessionInfo(
        user=await session_user(db, user.id) if user else None,
        gpc=gpc,
        demo_mode=get_settings().demo_mode,
        data_version=await current_data_version(db),
    )


async def update_settings(db: AsyncSession, user: CurrentUser, body: SettingsUpdate) -> SessionUser:
    """Update role, language, expert mode or the 16+ confirmation; returns the session user."""
    sets: list[str] = []
    params: dict[str, object] = {"uid": user.id}
    if body.role is not None:
        sets.append("role = :role")
        params["role"] = body.role.value
        if body.role != user.role:
            sets.append("role_verified = false")
            if body.expert_mode is None:  # expert mode is the default for researchers
                sets.append("expert_mode = :expert_default")
                params["expert_default"] = body.role == Role.researcher
    if body.language is not None:
        sets.append("language = :language")
        params["language"] = body.language
    if body.expert_mode is not None:
        sets.append("expert_mode = :expert")
        params["expert"] = body.expert_mode
    if body.age_confirmed_16:
        sets.append("age_confirmed_at = COALESCE(age_confirmed_at, now())")
    if sets:
        sets.append("updated_at = now()")
        await db.execute(
            text(f"UPDATE profiles SET {', '.join(sets)} WHERE user_id = :uid"), params
        )
    return await session_user(db, user.id)


# ---- consents -----------------------------------------------------------------------------

_CONSENT_COLUMNS = (
    "id, consent_type, version, granted_at, revoked_at, about_child,"
    " parental_responsibility_confirmed"
)


def _consent(row: Any) -> Consent:
    return Consent(
        id=row["id"],
        consent_type=ConsentType(row["consent_type"]),
        version=row["version"],
        granted_at=row["granted_at"],
        revoked_at=row["revoked_at"],
        about_child=row["about_child"],
        parental_responsibility_confirmed=row["parental_responsibility_confirmed"],
        active=row["revoked_at"] is None,
    )


async def _active_consent(db: AsyncSession, user_id: UUID, consent_type: ConsentType) -> Any:
    return (
        (
            await db.execute(
                text(
                    f"SELECT {_CONSENT_COLUMNS} FROM consents WHERE user_id = :uid"
                    " AND consent_type = :t AND revoked_at IS NULL FOR UPDATE"
                ),
                {"uid": user_id, "t": consent_type.value},
            )
        )
        .mappings()
        .first()
    )


async def list_consents(db: AsyncSession, user: CurrentUser) -> list[Consent]:
    """All of the user's consents, active and revoked (history is kept)."""
    rows = (
        await db.execute(
            text(
                f"SELECT {_CONSENT_COLUMNS} FROM consents WHERE user_id = :uid"
                " ORDER BY granted_at DESC, id"
            ),
            {"uid": user.id},
        )
    ).mappings()
    return [_consent(r) for r in rows]


async def grant_consent(db: AsyncSession, user: CurrentUser, body: ConsentGrant) -> Consent:
    """Grant a consent (idempotent while an identical one is active); stores version and time.

    A grant with a different text version or child scope supersedes the active one: the old row
    is closed (history stays) and contributions held under it move to the new row.
    """
    profile = await get_profile(db, user)
    if profile.about_child and not body.about_child:
        raise ApiError(
            422,
            ErrorCode.validation_error,
            "Your profile describes a child: confirm parental responsibility with this consent.",
        )

    existing = await _active_consent(db, user.id, body.consent_type)
    if existing is not None:
        same = (
            existing["version"] == body.version
            and existing["about_child"] == body.about_child
            and existing["parental_responsibility_confirmed"]
            == body.parental_responsibility_confirmed
        )
        if same:
            return _consent(existing)
        await db.execute(
            text("UPDATE consents SET revoked_at = now() WHERE id = :id"), {"id": existing["id"]}
        )

    try:
        async with db.begin_nested():
            row = (
                (
                    await db.execute(
                        text(
                            "INSERT INTO consents (user_id, consent_type, version, about_child,"
                            " parental_responsibility_confirmed)"
                            " VALUES (:uid, :t, :v, :child, :parental)"
                            f" RETURNING {_CONSENT_COLUMNS}"
                        ),
                        {
                            "uid": user.id,
                            "t": body.consent_type.value,
                            "v": body.version,
                            "child": body.about_child,
                            "parental": body.parental_responsibility_confirmed,
                        },
                    )
                )
                .mappings()
                .one()
            )
    except IntegrityError:  # a concurrent grant won the race
        raise ApiError(409, ErrorCode.conflict) from None

    if existing is not None:
        await db.execute(
            text(
                "UPDATE contributions SET consent_id = :new, updated_at = now()"
                " WHERE consent_id = :old"
            ),
            {"new": row["id"], "old": existing["id"]},
        )
    return _consent(row)


async def revoke_consent(db: AsyncSession, user: CurrentUser, consent_type: ConsentType) -> None:
    """Revoke and delete the data held under that consent (Art. 7(3)); 404 if none is active.

    upload: documents, findings, extraction jobs and the profile items that came from documents.
    contribute: every contribution, which removes it from the shared graph.
    """
    existing = await _active_consent(db, user.id, consent_type)
    if existing is None:
        raise ApiError(404, ErrorCode.not_found, "No active consent of this type.")
    await db.execute(
        text("UPDATE consents SET revoked_at = now() WHERE id = :id"), {"id": existing["id"]}
    )
    params = {"uid": user.id}
    if consent_type == ConsentType.health_data:
        await db.execute(text("DELETE FROM jobs WHERE user_id = :uid"), params)
        await db.execute(text("DELETE FROM documents WHERE user_id = :uid"), params)
        await db.execute(text("DELETE FROM findings WHERE user_id = :uid"), params)
        await remove_profile_items(db, user.id, source=ProfileSource.document)
    else:
        await db.execute(text("DELETE FROM contributions WHERE user_id = :uid"), params)
        await refresh_shared_graph(db, contributions=True)


# ---- patient profile ----------------------------------------------------------------------

_ID_PATTERNS = {
    "MONDO": re.compile(r"^MONDO:\d{7}$"),
    "HGNC": re.compile(r"^HGNC:\d{1,6}$"),
    "HP": re.compile(r"^HP:\d{7}$"),
    "CLINVAR": re.compile(r"^CLINVAR:\d{1,10}$"),
}
_GENE_SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,29}$")
_GENE_PREFIX = r"[A-Z0-9][A-Z0-9-]{0,14}(?:orf[0-9]{1,3}[A-Z0-9-]{0,5})?"  # HGNC symbol
_HGVS_TOKEN = r"[A-Za-z0-9_.:>+*()\[\];=,-]{3,200}"
# HGVS notation, optionally as a ClinVar label ("STXBP1 c.1216C>T") or variation name
# ("NM_003165.6(STXBP1):c.1216C>T (p.Arg406Cys)"). No free text, so no digit-run rule here.
_HGVS = re.compile(rf"^(?:{_GENE_PREFIX} )?{_HGVS_TOKEN}(?: \(p\.[A-Za-z0-9_*=?>]+\))?$")
_ONSET_LABEL = re.compile(r"^[A-Za-z][A-Za-z ,'-]{0,59}$")
_LONG_DIGITS = re.compile(r"\d{5,}")
_MAX_LABEL = 120
_MAX_ITEMS = 200


def _invalid(field: str) -> ApiError:
    return ApiError(422, ErrorCode.validation_error, f"Invalid request fields: {field}")


def _invalid_from(exc: ValidationError, fallback: str) -> ApiError:
    """422 naming the failing fields only (pydantic's inputs would echo user content)."""
    fields = sorted({".".join(str(p) for p in err.get("loc", ())) for err in exc.errors()})
    return _invalid(", ".join(f for f in fields if f) or fallback)


def _check_id(value: str | None, kind: str, field: str) -> None:
    if value is not None and not _ID_PATTERNS[kind].match(value):
        raise _invalid(field)


def _check_label(value: str, field: str) -> None:
    """Labels name ontology terms; reject anything that looks like contact data or an ID."""
    if (
        not value.strip()
        or len(value) > _MAX_LABEL
        or "@" in value
        or "://" in value
        or _LONG_DIGITS.search(value)
        or any(c in value for c in "\r\n\t")
    ):
        raise _invalid(field)


def _check_onset(value: str | None, field: str) -> None:
    if value is not None and not (_ID_PATTERNS["HP"].match(value) or _ONSET_LABEL.match(value)):
        raise _invalid(field)


def validate_profile(profile: PatientProfile) -> None:
    """Strict content checks beyond the schema (422 with field names only, never values)."""
    for name in ("diseases", "genes", "variants", "phenotypes"):
        if len(getattr(profile, name)) > _MAX_ITEMS:
            raise _invalid(name)
    for i, d in enumerate(profile.diseases):
        _check_id(d.id, "MONDO", f"diseases.{i}.id")
        _check_label(d.label, f"diseases.{i}.label")
    for i, g in enumerate(profile.genes):
        _check_id(g.id, "HGNC", f"genes.{i}.id")
        if not _GENE_SYMBOL.match(g.label):
            raise _invalid(f"genes.{i}.label")
    for i, v in enumerate(profile.variants):
        if v.hgvs is None and v.clinvar_id is None:
            raise _invalid(f"variants.{i}")
        if v.hgvs is not None and (len(v.hgvs) > 200 or not _HGVS.match(v.hgvs)):
            raise _invalid(f"variants.{i}.hgvs")
        _check_id(v.clinvar_id, "CLINVAR", f"variants.{i}.clinvar_id")
        _check_id(v.gene_id, "HGNC", f"variants.{i}.gene_id")
    for i, p in enumerate(profile.phenotypes):
        _check_id(p.id, "HP", f"phenotypes.{i}.id")
        _check_label(p.label, f"phenotypes.{i}.label")
        _check_onset(p.onset, f"phenotypes.{i}.onset")
    _check_onset(profile.onset, "onset")
    if profile.about_child and not profile.parental_responsibility_confirmed:
        # compliance.md, Children: data about a child needs parental responsibility.
        raise _invalid("parental_responsibility_confirmed")


def _item_key(item: ProfileItemModel) -> tuple[str, str]:
    if isinstance(item, ProfileVariant):
        return ("variants", item.clinvar_id or item.hgvs or "")
    if isinstance(item, ProfileDisease):
        return ("diseases", item.id)
    if isinstance(item, ProfileGene):
        return ("genes", item.id)
    return ("phenotypes", item.id)


def _stamp_and_dedupe(profile: PatientProfile) -> PatientProfile:
    """Every item carries a confirmation time; later duplicates replace earlier ones."""
    now = datetime.now(UTC)
    for name in ("diseases", "genes", "variants", "phenotypes"):
        merged: dict[tuple[str, str], ProfileItemModel] = {}
        for item in getattr(profile, name):
            if item.confirmed_at is None:
                item.confirmed_at = now
            merged[_item_key(item)] = item
        setattr(profile, name, list(merged.values()))
    return profile


def _profile_json(profile: PatientProfile) -> str:
    return json.dumps(profile.model_dump(mode="json", exclude={"updated_at"}))


def _load_profile(data: dict[str, Any] | None, updated_at: datetime | None) -> PatientProfile:
    try:
        profile = PatientProfile.model_validate({**(data or {}), "updated_at": None})
    except ValidationError as exc:
        raise _invalid_from(exc, "profile") from None
    profile.updated_at = updated_at
    return profile


async def _locked_profile(db: AsyncSession, user_id: UUID) -> PatientProfile:
    """The user's profile row, created if missing and locked for this transaction."""
    await db.execute(
        text("INSERT INTO patient_profiles (user_id) VALUES (:uid) ON CONFLICT DO NOTHING"),
        {"uid": user_id},
    )
    row = (
        (
            await db.execute(
                text(
                    "SELECT profile, updated_at FROM patient_profiles WHERE user_id = :uid"
                    " FOR UPDATE"
                ),
                {"uid": user_id},
            )
        )
        .mappings()
        .one()
    )
    return _load_profile(row["profile"], row["updated_at"])


async def _write_profile(
    db: AsyncSession, user_id: UUID, profile: PatientProfile
) -> PatientProfile:
    updated_at = await db.scalar(
        text(
            "UPDATE patient_profiles SET profile = CAST(:p AS jsonb),"
            " updated_at = clock_timestamp()"
            " WHERE user_id = :uid RETURNING updated_at"
        ),
        {"uid": user_id, "p": _profile_json(profile)},
    )
    profile.updated_at = updated_at
    return profile


async def get_profile(db: AsyncSession, user: CurrentUser) -> PatientProfile:
    """The user's PatientProfile (empty profile with updated_at null if none yet)."""
    row = (
        (
            await db.execute(
                text("SELECT profile, updated_at FROM patient_profiles WHERE user_id = :uid"),
                {"uid": user.id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return PatientProfile()
    return _load_profile(row["profile"], row["updated_at"])


async def put_profile(
    db: AsyncSession, user: CurrentUser, profile: PatientProfile
) -> PatientProfile:
    """Replace the PatientProfile (Art. 16: every field editable).

    Optimistic concurrency: `updated_at` must equal the value from the last GET (null when no
    profile exists yet); otherwise 409 conflict, so chat or document merges are never lost.
    """
    validate_profile(profile)
    current = await _locked_profile(db, user.id)
    has_content = current.model_dump(exclude={"updated_at"}) != PatientProfile().model_dump(
        exclude={"updated_at"}
    )
    expected = profile.updated_at
    if expected is None:
        if has_content:
            raise ApiError(409, ErrorCode.conflict, "The profile changed; reload and try again.")
    elif current.updated_at is None or expected != current.updated_at:
        raise ApiError(409, ErrorCode.conflict, "The profile changed; reload and try again.")
    if profile.about_child is False:
        profile.parental_responsibility_confirmed = False
    return await _write_profile(db, user.id, _stamp_and_dedupe(profile))


async def merge_profile_items(
    db: AsyncSession, user_id: UUID, items: Sequence[ProfileItemModel]
) -> PatientProfile:
    """Merge confirmed items (chat chips, document findings) into the user's profile.

    Call inside a transaction scoped to user_id. An item with the same key (ID, or ClinVar
    ID / HGVS for variants) replaces the stored one; `confirmed_at` defaults to now. Raises
    ApiError 422 if an item fails validation.
    """
    profile = await _locked_profile(db, user_id)
    for item in items:
        name, _ = _item_key(item)
        getattr(profile, name).append(item)
    _stamp_and_dedupe(profile)
    try:
        profile = PatientProfile.model_validate(profile.model_dump())
    except ValidationError as exc:
        raise _invalid_from(exc, "items") from None
    validate_profile(profile)
    return await _write_profile(db, user_id, profile)


async def remove_profile_items(
    db: AsyncSession,
    user_id: UUID,
    *,
    finding_ids: Iterable[UUID] | None = None,
    source: ProfileSource | None = None,
) -> PatientProfile | None:
    """Remove profile items that came from the given findings and/or source.

    Call inside a transaction scoped to user_id. Returns None if the user has no profile.
    """
    exists = await db.scalar(
        text("SELECT 1 FROM patient_profiles WHERE user_id = :uid"), {"uid": user_id}
    )
    if not exists:
        return None
    ids = set(finding_ids or ())
    profile = await _locked_profile(db, user_id)

    def keep(item: ProfileItemModel) -> bool:
        if source is not None and item.source == source:
            return False
        if source == ProfileSource.document and item.finding_id is not None:
            return False
        return item.finding_id is None or item.finding_id not in ids

    for name in ("diseases", "genes", "variants", "phenotypes"):
        setattr(profile, name, [i for i in getattr(profile, name) if keep(i)])
    return await _write_profile(db, user_id, profile)


# ---- data rights --------------------------------------------------------------------------


async def _rows(db: AsyncSession, sql: str, user_id: UUID) -> list[Any]:
    return list((await db.execute(text(sql), {"uid": user_id})).mappings())


def _reply(data: dict[str, Any] | None) -> AgentReply | None:
    if data is None:
        return None
    try:
        return AgentReply.model_validate(data)
    except ValidationError:
        log.warning("stored chat reply does not match AgentReply; exported without it")
        return None


async def export_data(db: AsyncSession, user: CurrentUser) -> DataExport:
    """All user data as JSON (GDPR Art. 15/20, CCPA right to know). Token values excluded."""
    uid = user.id
    account = (
        await _rows(
            db, "SELECT id, email, name, created_at, last_login_at FROM users WHERE id = :uid", uid
        )
    )[0]
    settings = (
        await _rows(
            db,
            "SELECT role, role_verified, orcid_id, language, expert_mode, gpc_opt_out,"
            " age_confirmed_at FROM profiles WHERE user_id = :uid",
            uid,
        )
    )[0]
    tokens = await _rows(
        db,
        "SELECT scopes, expires_at, created_at, updated_at FROM openai_tokens WHERE user_id = :uid",
        uid,
    )
    connection = (
        OpenAIConnection(
            scopes=list(tokens[0]["scopes"] or []),
            expires_at=tokens[0]["expires_at"],
            connected_at=tokens[0]["created_at"],
            updated_at=tokens[0]["updated_at"],
        )
        if tokens
        else None
    )
    consents = await _rows(
        db,
        f"SELECT {_CONSENT_COLUMNS} FROM consents WHERE user_id = :uid ORDER BY granted_at, id",
        uid,
    )
    profile_rows = await _rows(
        db, "SELECT profile, updated_at FROM patient_profiles WHERE user_id = :uid", uid
    )
    sessions = await _rows(
        db,
        "SELECT id, title, created_at, updated_at FROM chat_sessions WHERE user_id = :uid"
        " ORDER BY created_at, id",
        uid,
    )
    messages = await _rows(
        db,
        "SELECT id, session_id, role, content, reply, created_at FROM chat_messages"
        " WHERE user_id = :uid ORDER BY created_at, id",
        uid,
    )
    by_session: dict[UUID, list[ChatMessage]] = {}
    for m in messages:
        by_session.setdefault(m["session_id"], []).append(
            ChatMessage(
                id=m["id"],
                session_id=m["session_id"],
                role=m["role"],
                content=m["content"],
                reply=_reply(m["reply"]),
                created_at=m["created_at"],
            )
        )
    documents = await _rows(
        db,
        "SELECT id, status, doc_type, page_count, created_at, raw_deleted_at FROM documents"
        " WHERE user_id = :uid ORDER BY created_at, id",
        uid,
    )
    findings = await _rows(
        db,
        "SELECT id, document_id, type, value, normalized_id, page, snippet, confirmed, payload,"
        " decided_at FROM findings WHERE user_id = :uid ORDER BY created_at, id",
        uid,
    )
    contributions = await _rows(
        db,
        "SELECT id, kind, payload, status, consent_id, created_at FROM contributions"
        " WHERE user_id = :uid ORDER BY created_at, id",
        uid,
    )
    flags = await _rows(
        db,
        "SELECT id, edge_id, reason, status, created_at FROM edge_flags WHERE user_id = :uid"
        " ORDER BY created_at, id",
        uid,
    )
    jobs = await _rows(
        db,
        "SELECT id, kind, status, progress, document_id, error, created_at FROM jobs"
        " WHERE user_id = :uid ORDER BY created_at, id",
        uid,
    )
    return DataExport(
        exported_at=datetime.now(UTC),
        account=AccountInfo.model_validate(dict(account)),
        settings=ProfileSettings.model_validate(dict(settings)),
        openai_connected=connection is not None,
        openai_connection=connection,
        consents=[_consent(r) for r in consents],
        patient_profile=(
            _load_profile(profile_rows[0]["profile"], profile_rows[0]["updated_at"])
            if profile_rows
            else None
        ),
        chat_sessions=[
            ChatSessionExport(
                session=ChatSession.model_validate(dict(s)),
                messages=by_session.get(s["id"], []),
            )
            for s in sessions
        ],
        documents=[Document.model_validate(dict(d)) for d in documents],
        findings=[Finding.model_validate(dict(f)) for f in findings],
        contributions=[contribution_from_row(c) for c in contributions],
        edge_flags=[EdgeFlag.model_validate(dict(f)) for f in flags],
        jobs=[Job.model_validate(dict(j)) for j in jobs],
    )


async def _revoke_openai_tokens(db: AsyncSession, user: CurrentUser) -> None:
    """Best effort: revoke the ChatGPT tokens through the auth service if it offers logout."""
    try:
        from backend.api.services import auth as auth_service
    except Exception as exc:  # noqa: BLE001 - deletion must work without the auth service
        log.info("auth service unavailable for token revocation: %s", type(exc).__name__)
        return
    logout = getattr(auth_service, "logout", None)
    if logout is None:
        return
    try:
        async with db.begin_nested():
            await logout(db, user, Response())
    except Exception as exc:  # noqa: BLE001 - revocation is best effort
        log.info("token revocation skipped: %s", type(exc).__name__)


async def delete_account(db: AsyncSession, user: CurrentUser) -> None:
    """Delete the user row; ON DELETE CASCADE removes everything else.

    Revokes the OpenAI tokens first (best effort) and refreshes the shared-graph overlays so the
    user's contributions and flags disappear for everyone. The route clears the session cookie.
    """
    await _revoke_openai_tokens(db, user)
    deleted = await db.scalar(
        text("DELETE FROM users WHERE id = :uid RETURNING id"), {"uid": user.id}
    )
    if deleted is None:
        raise ApiError(401, ErrorCode.sign_in_required)
    await refresh_shared_graph(db, contributions=True, flags=True)
