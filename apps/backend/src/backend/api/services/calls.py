"""Calls: surveys, studies and trials that verified professionals publish.

Who may write: a doctor or researcher whose public card is visible and verified (the definer
function professional_cards() lists them; `publisher_card` is the single check). Writing is
contract-based (publisher terms), no consent type. Reading published calls needs only a signed-in
16+ account: no health data is processed and nothing about the reader is stored.

Two modes, chosen by the setting CALLS_REVIEW_REQUIRED (default false):
- Self-publishing (default): submit runs the wording check, the atlas check and the publisher
  check and publishes the call at once through the definer function publish_own_call(), which
  re-checks ownership and the card, marks the call `self_published` and logs it in call_reviews.
  Such a call says "Published by the expert. Not reviewed by the Amber team."
- Review: draft -> pending_review (submit, same checks) -> published or rejected by the operator
  (`backend.cli calls ...`, definer function review_call(), logged in call_reviews).

The publisher may edit a draft, a rejected call or one still pending review (it goes back to
draft); a published call is never edited (close it and write a new one). Closing ends a published
call (closed) or pulls an unpublished one (withdrawn). The database enforces that a call goes
live only through one of the two definer functions (trigger calls_guard).

Hard limits ("to get medication"): a call describes research that looks for participants. The
wording check refuses offers, promises and prices of treatments in both modes; in review mode
the operator checks the rest.
"""

import re
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.api.services.graph import get_graph
from backend.api.services.people import card_from_row
from backend.config import get_settings
from backend.schemas.account import CurrentUser
from backend.schemas.calls import (
    MAX_OPEN_CALLS,
    REVIEW_BADGE,
    SELF_PUBLISHED_BADGE,
    AtlasRef,
    Call,
    CallExport,
    CallInput,
    CallKind,
    CallList,
    CallReviewExport,
    CallStatus,
    OwnCall,
    OwnCallList,
    RequestedField,
    WordingIssue,
)
from backend.schemas.enums import ErrorCode, NodeType
from backend.schemas.people import PublicCard

OPEN_STATUSES = (CallStatus.draft, CallStatus.pending_review, CallStatus.published)
EDITABLE_STATUSES = (CallStatus.draft, CallStatus.pending_review, CallStatus.rejected)
SUBMITTABLE_STATUSES = (CallStatus.draft, CallStatus.rejected)
# Self-publishing never takes a rejected call live as it is: it must be edited first (-> draft).
SELF_PUBLISHABLE_STATUSES = (CallStatus.draft, CallStatus.pending_review)
INSUFFICIENT_PRIVILEGE = "42501"
RUN_BY_TYPES = frozenset(
    {NodeType.institution, NodeType.patient_org, NodeType.network, NodeType.registry}
)
WORDING_FIELDS = (
    "title",
    "summary",
    "participation",
    "eligibility_text",
    "run_by_label",
    "ethics_body",
)

# The wording check on submit. Coarse on purpose: it catches the phrases that offer, promise or
# price a treatment; the operator reviews the rest. English and German.
WORDING_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (term, re.compile(pattern, re.IGNORECASE))
    for term, pattern in (
        ("cure", r"(?<!\bno\s)(?<!\bnot\sa\s)\bcur(?:e|es|ed|ing|ative)\b"),
        (
            "treatment available",
            r"\b(?:treatments?|therap(?:y|ies)|drugs?)\s+(?:is\s+|are\s+)?"
            r"(?:now\s+)?available\b",
        ),
        (
            "free medication",
            r"\bfree(?:\s+of\s+charge)?\s+(?:medications?|medicines?|drugs?|"
            r"treatments?|therap(?:y|ies))\b",
        ),
        ("guaranteed", r"\bguarantee(?:d|s)?\b"),
        ("miracle", r"\bmiracle\b"),
        ("breakthrough", r"\bbreakthrough\b"),
        ("risk-free", r"\brisk[\s-]?free\b|\bno\s+side[\s-]effects\b"),
        ("100% safe or effective", r"\b100\s*%\s*(?:safe|effective)\b"),
        ("proven to work", r"\bproven\s+(?:to\s+work|effective|treatment|therapy|cure)\b"),
        (
            "get medication",
            r"\bget\s+(?:the\s+|your\s+|new\s+)?(?:medications?|medicines?|"
            r"drugs?)\b",
        ),
        (
            "access to treatment",
            r"\b(?:get|gain|guaranteed)\s+access\s+to\s+(?:the\s+|a\s+|new\s+)?"
            r"(?:medications?|medicines?|drugs?|treatments?|therap(?:y|ies))\b",
        ),
        ("price", r"\b(?:price[sd]?|pricing|buy|purchase|for\s+sale|order\s+now|discount)\b"),
        ("Heilung", r"\bheil(?:ung|t|en|bar)\b"),
        ("garantiert", r"\bgarantier\w*"),
        ("kostenlose Medikamente", r"\bkostenlos\w*\s+(?:medikament|arznei|behandlung|therapie)"),
        (
            "Behandlung verfügbar",
            r"\b(?:behandlung|therapie|medikament)\w*\s+(?:ist\s+|sind\s+)?"
            r"(?:jetzt\s+)?verfügbar",
        ),
        ("Wundermittel", r"\bwunder(?:mittel|heilung)\w*"),
    )
)

_CALL_COLUMNS = (
    "c.id, c.kind, c.title, c.summary, c.participation, c.eligibility_text, c.disease_ids,"
    " c.gene_ids, c.phenotype_ids, c.min_age, c.max_age, c.children_ok, c.countries, c.remote,"
    " c.run_by_label, c.run_by_node_id, c.ethics_body, c.ethics_reference, c.registry_id,"
    " c.external_url, c.opens_at, c.closes_at, c.max_signups, c.requested_fields, c.status,"
    " c.review_note, c.submitted_at, c.reviewed_at, c.published_at, c.closed_at, c.demo,"
    " c.self_published, c.created_at, c.updated_at"
)
_CARD_COLUMNS = (
    "pc.card_id, pc.role, pc.name, pc.name_verified, pc.institutions, pc.orcid_id,"
    " pc.atlas_node_id, pc.headline, pc.accepts_patient_messages, pc.verification_method"
)
_NOT_EXPIRED = "(c.closes_at IS NULL OR c.closes_at >= current_date)"
_PUBLISHED_SQL = f"""
    SELECT {_CALL_COLUMNS}, {_CARD_COLUMNS}
      FROM calls c
      JOIN call_publisher_cards() cp ON cp.call_id = c.id
      JOIN professional_cards() pc ON pc.card_id = cp.card_id
     WHERE c.status = 'published' AND {_NOT_EXPIRED}
"""
# The user's own card, exactly as others see it (or no row while it is hidden or unverified).
_OWN_CARD_SQL = text(
    f"SELECT {_CARD_COLUMNS} FROM professional_cards() pc"
    " WHERE pc.card_id = (SELECT p.card_id FROM profiles p WHERE p.user_id = :uid)"
)
_WRITE_COLUMNS = (
    "kind",
    "title",
    "summary",
    "participation",
    "eligibility_text",
    "disease_ids",
    "gene_ids",
    "phenotype_ids",
    "min_age",
    "max_age",
    "children_ok",
    "countries",
    "remote",
    "run_by_label",
    "run_by_node_id",
    "ethics_body",
    "ethics_reference",
    "registry_id",
    "external_url",
    "opens_at",
    "closes_at",
    "max_signups",
    "requested_fields",
)


def _invalid(field: str) -> ApiError:
    return ApiError(422, ErrorCode.validation_error, f"Invalid request fields: {field}")


def _not_found() -> ApiError:
    return ApiError(404, ErrorCode.not_found, "No such call.")


# ---- wording and validation ---------------------------------------------------------------


def wording_issues(values: dict[str, Any]) -> list[WordingIssue]:
    """Every (field, rule) the wording check refuses, in field order."""
    issues: list[WordingIssue] = []
    for field in WORDING_FIELDS:
        value = values.get(field)
        if not isinstance(value, str) or not value:
            continue
        for term, pattern in WORDING_RULES:
            if pattern.search(value):
                issues.append(WordingIssue(field=field, term=term))
    return issues


def _check_wording(values: dict[str, Any]) -> None:
    issues = wording_issues(values)
    if issues:
        found = ", ".join(f"{i.field} ('{i.term}')" for i in issues)
        raise ApiError(
            422,
            ErrorCode.validation_error,
            "Calls describe research looking for participants and must not offer, promise or "
            f"price a treatment. Rephrase: {found}",
        )


def _check_rules(body: CallInput) -> None:
    """Cross-field rules and atlas IDs (422 naming the field, never the value)."""
    if body.kind in (CallKind.study, CallKind.trial) and not body.ethics_reference:
        raise _invalid("ethics_reference")
    if body.kind == CallKind.trial and not body.registry_id:
        raise _invalid("registry_id")
    if body.min_age is not None and body.max_age is not None and body.min_age > body.max_age:
        raise _invalid("max_age")
    if body.opens_at and body.closes_at and body.opens_at > body.closes_at:
        raise _invalid("closes_at")
    nodes = get_graph().nodes
    for name, ids, node_type in (
        ("disease_ids", body.disease_ids, NodeType.disease),
        ("gene_ids", body.gene_ids, NodeType.gene),
        ("phenotype_ids", body.phenotype_ids, NodeType.phenotype),
    ):
        for i, node_id in enumerate(ids):
            node = nodes.get(node_id)
            if node is None or node.type != node_type:
                raise _invalid(f"{name}.{i}")
    if body.run_by_node_id is not None:
        node = nodes.get(body.run_by_node_id)
        if node is None or node.type not in RUN_BY_TYPES:
            raise _invalid("run_by_node_id")


def _check_stored(row: Any) -> None:
    """Re-check a stored call before it goes to review (the atlas may have changed)."""
    try:
        body = CallInput.model_validate({c: row[c] for c in _WRITE_COLUMNS})
    except ValueError:
        raise _invalid("call") from None
    _check_rules(body)
    if body.closes_at is not None and body.closes_at < date.today():
        raise _invalid("closes_at")
    _check_wording(row)


# ---- the publisher check (single seam on connect stage 2) --------------------------------


async def publisher_card(db: AsyncSession, user: CurrentUser) -> PublicCard | None:
    """The user's public card if they may publish calls: a doctor or researcher whose card is
    visible and verified, i.e. listed by professional_cards(). None otherwise."""
    row = (await db.execute(_OWN_CARD_SQL, {"uid": user.id})).mappings().first()
    return card_from_row(row) if row is not None else None


async def _require_publisher(db: AsyncSession, user: CurrentUser) -> PublicCard:
    card = await publisher_card(db, user)
    if card is None:
        raise ApiError(
            403,
            ErrorCode.forbidden,
            "Only verified doctors and researchers with a visible public card can publish calls.",
        )
    return card


# ---- rows -> responses --------------------------------------------------------------------


def _refs(ids: list[str] | None) -> list[AtlasRef]:
    nodes = get_graph().nodes
    out = []
    for node_id in ids or []:
        node = nodes.get(node_id)
        out.append(AtlasRef(id=node_id, label=node.label if node is not None else None))
    return out


def registry_url(registry_id: str | None) -> str | None:
    if not registry_id:
        return None
    if registry_id.startswith("NCT"):
        return f"https://clinicaltrials.gov/study/{registry_id}"
    if registry_id.startswith("DRKS"):
        return f"https://drks.de/search/en/trial/{registry_id}"
    if re.fullmatch(r"\d{4}-\d{6}-\d{2}-\d{2}", registry_id):
        return f"https://euclinicaltrials.eu/search-for-clinical-trials/?lang=en&EUCT={registry_id}"
    return f"https://www.clinicaltrialsregister.eu/ctr-search/search?query={registry_id}"


def review_required() -> bool:
    return get_settings().calls_review_required


def _review_badge(row: Any) -> str:
    """What a call says about its review: for one that went live, how it went live; for one
    that has not, the badge it would get in the current mode."""
    if row["published_at"] is not None:
        return SELF_PUBLISHED_BADGE if row["self_published"] else REVIEW_BADGE
    return REVIEW_BADGE if review_required() else SELF_PUBLISHED_BADGE


def _call_fields(row: Any, publisher: PublicCard | None) -> dict[str, Any]:
    run_by = _refs([row["run_by_node_id"]])[0] if row["run_by_node_id"] else None
    return {
        "id": row["id"],
        "kind": CallKind(row["kind"]),
        "title": row["title"],
        "summary": row["summary"],
        "participation": row["participation"],
        "eligibility_text": row["eligibility_text"],
        "diseases": _refs(row["disease_ids"]),
        "genes": _refs(row["gene_ids"]),
        "phenotypes": _refs(row["phenotype_ids"]),
        "min_age": row["min_age"],
        "max_age": row["max_age"],
        "adults_only": row["min_age"] is not None and row["min_age"] >= 18,
        "children_ok": row["children_ok"],
        "countries": list(row["countries"] or []),
        "remote": row["remote"],
        "run_by_label": row["run_by_label"],
        "run_by_node": run_by,
        "ethics_body": row["ethics_body"],
        "ethics_reference": row["ethics_reference"],
        "registry_id": row["registry_id"],
        "registry_url": registry_url(row["registry_id"]),
        "external_url": row["external_url"],
        "opens_at": row["opens_at"],
        "closes_at": row["closes_at"],
        "max_signups": row["max_signups"],
        "requested_fields": [RequestedField(f) for f in row["requested_fields"] or []],
        "publisher": publisher,
        "published_at": row["published_at"],
        "demo": row["demo"],
        "self_published": row["self_published"],
        "review_badge": _review_badge(row),
    }


def _public(row: Any) -> Call:
    return Call(**_call_fields(row, card_from_row(row)))


def _own(row: Any, card: PublicCard | None) -> OwnCall:
    status = CallStatus(row["status"])
    expired = row["closes_at"] is not None and row["closes_at"] < date.today()
    return OwnCall(
        **_call_fields(row, card),
        status=status,
        review_note=row["review_note"],
        submitted_at=row["submitted_at"],
        reviewed_at=row["reviewed_at"],
        closed_at=row["closed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expired=status == CallStatus.published and expired,
        editable=status in EDITABLE_STATUSES,
        wording_issues=wording_issues(row),
    )


# ---- reading ------------------------------------------------------------------------------


async def list_published(db: AsyncSession, kind: CallKind | None) -> CallList:
    sql = _PUBLISHED_SQL + (" AND c.kind = :kind" if kind else "")
    sql += " ORDER BY c.published_at DESC, c.id"
    rows = (await db.execute(text(sql), {"kind": kind.value} if kind else {})).mappings()
    return CallList(items=[_public(r) for r in rows])


async def get_published(db: AsyncSession, call_id: UUID) -> Call:
    row = (
        (await db.execute(text(_PUBLISHED_SQL + " AND c.id = :id"), {"id": call_id}))
        .mappings()
        .first()
    )
    if row is None:
        raise _not_found()
    return _public(row)


async def _own_row(db: AsyncSession, user: CurrentUser, call_id: UUID, *, lock: bool = False):
    row = (
        (
            await db.execute(
                text(
                    f"SELECT {_CALL_COLUMNS} FROM calls c"
                    " WHERE c.id = :id AND c.publisher_id = :uid" + (" FOR UPDATE" if lock else "")
                ),
                {"id": call_id, "uid": user.id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise _not_found()
    return row


async def list_own(db: AsyncSession, user: CurrentUser) -> OwnCallList:
    card = await publisher_card(db, user)
    rows = (
        await db.execute(
            text(
                f"SELECT {_CALL_COLUMNS} FROM calls c WHERE c.publisher_id = :uid"
                " ORDER BY c.created_at DESC, c.id"
            ),
            {"uid": user.id},
        )
    ).mappings()
    return OwnCallList(
        items=[_own(r, card) for r in rows],
        can_publish=card is not None,
        review_required=review_required(),
    )


async def get_own(db: AsyncSession, user: CurrentUser, call_id: UUID) -> OwnCall:
    row = await _own_row(db, user, call_id)
    return _own(row, await publisher_card(db, user))


# ---- writing ------------------------------------------------------------------------------


def _params(body: CallInput) -> dict[str, Any]:
    values = body.model_dump(include=set(_WRITE_COLUMNS))
    values["kind"] = body.kind.value
    values["requested_fields"] = [f.value for f in body.requested_fields]
    return values


async def create(db: AsyncSession, user: CurrentUser, body: CallInput) -> OwnCall:
    card = await _require_publisher(db, user)
    _check_rules(body)
    # Serialize per publisher so the open-call limit holds under concurrent requests.
    await db.execute(
        text("SELECT 1 FROM profiles WHERE user_id = :uid FOR UPDATE"), {"uid": user.id}
    )
    open_count = await db.scalar(
        text("SELECT count(*) FROM calls WHERE publisher_id = :uid AND status = ANY(:open)"),
        {"uid": user.id, "open": [s.value for s in OPEN_STATUSES]},
    )
    if (open_count or 0) >= MAX_OPEN_CALLS:
        raise ApiError(
            409,
            ErrorCode.conflict,
            f"You can have at most {MAX_OPEN_CALLS} draft, pending or published calls.",
        )
    columns = ", ".join(_WRITE_COLUMNS)
    values = ", ".join(f":{c}" for c in _WRITE_COLUMNS)
    call_id = await db.scalar(
        text(f"INSERT INTO calls (publisher_id, {columns}) VALUES (:uid, {values}) RETURNING id"),
        {"uid": user.id, **_params(body)},
    )
    return _own(await _own_row(db, user, call_id), card)


async def update(db: AsyncSession, user: CurrentUser, call_id: UUID, body: CallInput) -> OwnCall:
    """Replace a draft, rejected or pending call; it becomes a draft again (submit again)."""
    card = await _require_publisher(db, user)
    row = await _own_row(db, user, call_id, lock=True)
    if CallStatus(row["status"]) not in EDITABLE_STATUSES:
        raise ApiError(
            409,
            ErrorCode.conflict,
            "Published, closed and withdrawn calls cannot be edited. Close it and write a new one.",
        )
    _check_rules(body)
    sets = ", ".join(f"{c} = :{c}" for c in _WRITE_COLUMNS)
    await db.execute(
        text(
            f"UPDATE calls SET {sets}, status = 'draft', submitted_at = NULL, updated_at = now()"
            " WHERE id = :id"
        ),
        {"id": call_id, **_params(body)},
    )
    return _own(await _own_row(db, user, call_id), card)


async def _publish_own(db: AsyncSession, user: CurrentUser, call_id: UUID, row: Any) -> None:
    """Self-publishing: the same checks as a submit, then publish_own_call(), which re-checks
    ownership and the card in the database and writes the log row."""
    status = CallStatus(row["status"])
    if status not in SELF_PUBLISHABLE_STATUSES:
        raise ApiError(
            409,
            ErrorCode.conflict,
            "Only drafts can be published. Edit a rejected call first; closed and withdrawn "
            "calls stay closed.",
        )
    _check_stored(row)
    try:
        await db.execute(text("SELECT publish_own_call(:id)"), {"id": call_id})
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) != INSUFFICIENT_PRIVILEGE:
            raise
        raise ApiError(409, ErrorCode.conflict, "The call could not be published.") from None


async def submit(db: AsyncSession, user: CurrentUser, call_id: UUID) -> OwnCall:
    """Publish the call (default), or with CALLS_REVIEW_REQUIRED send a draft (or a rejected
    call) to the Amber team for review. Idempotent once it is published or pending."""
    card = await _require_publisher(db, user)
    row = await _own_row(db, user, call_id, lock=True)
    status = CallStatus(row["status"])
    if not review_required():
        if status == CallStatus.published:
            return _own(row, card)
        await _publish_own(db, user, call_id, row)
        return _own(await _own_row(db, user, call_id), card)
    if status == CallStatus.pending_review:
        return _own(row, card)
    if status not in SUBMITTABLE_STATUSES:
        raise ApiError(409, ErrorCode.conflict, "Only drafts and rejected calls can be submitted.")
    _check_stored(row)
    await db.execute(
        text(
            "UPDATE calls SET status = 'pending_review', submitted_at = now(), updated_at = now()"
            " WHERE id = :id"
        ),
        {"id": call_id},
    )
    return _own(await _own_row(db, user, call_id), card)


async def close(db: AsyncSession, user: CurrentUser, call_id: UUID) -> OwnCall:
    """End a published call (closed) or pull an unpublished one (withdrawn). Idempotent."""
    row = await _own_row(db, user, call_id, lock=True)
    status = CallStatus(row["status"])
    if status in (CallStatus.draft, CallStatus.pending_review, CallStatus.rejected):
        new = CallStatus.withdrawn
    elif status == CallStatus.published:
        new = CallStatus.closed
    else:
        return _own(row, await publisher_card(db, user))
    await db.execute(
        text(
            "UPDATE calls SET status = :status, closed_at = now(), updated_at = now()"
            " WHERE id = :id"
        ),
        {"id": call_id, "status": new.value},
    )
    return _own(await _own_row(db, user, call_id), await publisher_card(db, user))


async def delete(db: AsyncSession, user: CurrentUser, call_id: UUID) -> None:
    """Delete one of the user's calls in any status, with its review log."""
    deleted = await db.scalar(
        text("DELETE FROM calls WHERE id = :id AND publisher_id = :uid RETURNING id"),
        {"id": call_id, "uid": user.id},
    )
    if deleted is None:
        raise _not_found()


# ---- data rights --------------------------------------------------------------------------


async def end_all(db: AsyncSession, user_id: UUID) -> None:
    """The switch to the patient role: close published calls, withdraw unpublished ones. The
    rows stay (the user can export or delete them)."""
    await db.execute(
        text(
            "UPDATE calls SET status = CASE WHEN status = 'published' THEN 'closed'"
            " ELSE 'withdrawn' END, closed_at = now(), updated_at = now()"
            " WHERE publisher_id = :uid"
            " AND status IN ('draft', 'pending_review', 'published', 'rejected')"
        ),
        {"uid": user_id},
    )


async def export(
    db: AsyncSession, user_id: UUID
) -> tuple[list[CallExport], list[CallReviewExport]]:
    calls = (
        await db.execute(
            text(
                f"SELECT {_CALL_COLUMNS} FROM calls c WHERE c.publisher_id = :uid"
                " ORDER BY c.created_at, c.id"
            ),
            {"uid": user_id},
        )
    ).mappings()
    reviews = (
        await db.execute(
            text(
                "SELECT call_id, action, note, created_at FROM call_reviews"
                " WHERE publisher_id = :uid ORDER BY created_at, id"
            ),
            {"uid": user_id},
        )
    ).mappings()
    return (
        [CallExport.model_validate(dict(r)) for r in calls],
        [CallReviewExport.model_validate(dict(r)) for r in reviews],
    )
