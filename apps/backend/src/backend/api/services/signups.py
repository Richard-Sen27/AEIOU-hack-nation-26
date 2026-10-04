"""Sign-ups to calls (connect stage 4, `connect` consent).

A patient or caregiver signs up to a published call and sends exactly the items they tick on the
sign-up screen to the call's publisher; only confirmed, non-excluded profile items that the call
asks for (`requested_fields`) and targets (its diseases, genes, symptoms) can be ticked. The
sign-up is an authorization stored with its text version and time and the named recipient. A user
aged 16 or 17 (self-declared age group) also ticks the guardian checkbox, stored on the row; the
publisher then sees "Participant is 16 or 17; a parent or guardian agreed (self-declared)". A call
for adults (min_age 18 or more) takes no sign-ups from a 16- or 17-year-old.

Row-level security (migration d7f2a9c4e6b1): the patient has full access to their own rows (the
trigger call_signups_guard allows only withdrawing and linking the conversation); the publisher
reads the sign-ups of their own calls; the publisher declines through decline_call_signup(). The
trigger call_signups_admit admits a sign-up only to a published, open call of somebody else with
a visible card, below max_signups.

Retention: withdrawing (or a decline) clears the shared items and the note at once and keeps a
stub for 30 days; sign-ups of a call that closed are deleted 90 days later (a deleted call turns
them into stubs at once). Rows past their time are deleted when the patient next lists their
sign-ups and by `backend.cli purge-messages` (daily); the publisher never sees them.
"""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.api.services import calls as calls_service
from backend.api.services import connect, messaging, suggestions
from backend.schemas.account import CurrentUser
from backend.schemas.calls import Call, RequestedField
from backend.schemas.enums import AgeRange, ErrorCode, Role
from backend.schemas.messaging import GUARDIAN_TEXT, GUARDIAN_TEXT_VERSION, AgeGroup
from backend.schemas.profile import PatientProfile
from backend.schemas.signups import (
    AUTHORIZATION_TEXT,
    AUTHORIZATION_VERSION,
    CLOSED_DAYS,
    FOR_ADULTS_LABEL,
    MINOR_LABEL,
    MySignup,
    MySignupList,
    ReceivedSignup,
    ReceivedSignupList,
    SharedItem,
    SharedItems,
    SignupAvailability,
    SignupBlock,
    SignupExport,
    SignupOption,
    SignupOptionKind,
    SignupOptions,
    SignupRequest,
    SignupsExport,
    SignupStatus,
)

_COLUMNS = (
    "s.id, s.call_id, s.call_title_snapshot, s.recipient_name, s.display_name, s.shared,"
    " s.about_child, s.note, s.authorization_version, s.authorized_at, s.guardian_agreed_at,"
    " s.guardian_text_version, s.status, s.withdrawn_at, s.declined_at, s.call_ended_at,"
    " s.purge_after, s.thread_id, s.created_at"
)
# Past its time: a stub after 30 days, a sign-up of a closed call 90 days after it closed, or a
# sign-up of a call that ended by its closing date (snapshot on the row) 90 days ago.
_EXPIRED = (
    "COALESCE(s.purge_after < now() OR (s.status IN ('active', 'call_closed')"
    f" AND s.call_closes_at < current_date - {CLOSED_DAYS}), false)"
)
PURGE_ALL_SQL = f"DELETE FROM call_signups s WHERE {_EXPIRED}"  # operator CLI (atlas_owner)
_PURGE_OWN_SQL = text(f"DELETE FROM call_signups s WHERE s.patient_id = :uid AND {_EXPIRED}")

_NOT_PATIENT = ApiError(
    403, ErrorCode.forbidden, "Only patients and caregivers can sign up to calls."
)
_DB_ERRORS = {
    "amber:full": ApiError(409, ErrorCode.conflict, "This call has all the sign-ups it can take."),
    "amber:closed": ApiError(409, ErrorCode.conflict, "This call is closed and takes no sign-ups."),
    "amber:own_call": ApiError(409, ErrorCode.conflict, "You cannot sign up to your own call."),
    "amber:not_available": ApiError(
        409,
        ErrorCode.conflict,
        "The team that runs this call cannot receive sign-ups at the moment.",
    ),
}


def _invalid(field: str) -> ApiError:
    return ApiError(422, ErrorCode.validation_error, f"Invalid request fields: {field}")


def _not_found() -> ApiError:
    return ApiError(404, ErrorCode.not_found, "Sign-up not found.")


def _db_error(exc: DBAPIError) -> ApiError | None:
    message = str(getattr(exc, "orig", "") or "")
    return next((err for marker, err in _DB_ERRORS.items() if marker in message), None)


# ---- what can be shared ---------------------------------------------------------------------


def age_range(profile: PatientProfile) -> str | None:
    if profile.age_range is not None:
        return profile.age_range.value
    if profile.age_years is None:
        return None
    for value, (low, high) in suggestions.AGE_BOUNDS.items():
        if low <= profile.age_years <= high and not (
            value == AgeRange.under_1 and profile.age_years == 1
        ):
            return value.value
    return None


def _variant_key(v: Any) -> str | None:
    key = v.clinvar_id or v.hgvs
    return f"variant:{key}" if key else None


def _offer(call: Call, profile: PatientProfile) -> dict[str, tuple[SignupOption, Any]]:
    """The options for this call and profile, keyed by option key, each with what it shares."""
    fields = set(call.requested_fields)
    labels = {r.id: r.label for r in (*call.diseases, *call.genes, *call.phenotypes)}
    t = suggestions.targets(profile)
    out: dict[str, tuple[SignupOption, Any]] = {}

    def add(key: str, kind: SignupOptionKind, label: str, value: Any, *, detail=None, pre=False):
        out[key] = (
            SignupOption(key=key, kind=kind, label=label, detail=detail, preselected=pre),
            value,
        )

    if RequestedField.diagnosis in fields:
        for d in profile.diseases:
            if d.id in t.diseases and d.id in labels:
                label = labels[d.id] or d.label
                add(f"diagnosis:{d.id}", SignupOptionKind.diagnosis, label,
                    SharedItem(id=d.id, label=label), pre=True)  # fmt: skip
    if RequestedField.genetic_findings in fields:
        for g in profile.genes:
            if g.id in t.genes and g.id in labels:
                label = labels[g.id] or g.label
                add(f"gene:{g.id}", SignupOptionKind.gene, label, SharedItem(id=g.id, label=label))
        for v in profile.variants:
            key = _variant_key(v)
            if key is None or v.confirmed_at is None or v.gene_id not in labels:
                continue
            gene = labels.get(v.gene_id) or v.gene_id or ""
            notation = v.hgvs or v.clinvar_id or ""
            detail = ", ".join(
                x.value.replace("_", " ") for x in (v.classification, v.zygosity) if x is not None
            )
            label = f"{gene} {notation}".strip()
            add(key, SignupOptionKind.variant, label,
                SharedItem(id=v.clinvar_id, label=label, detail=detail or None),
                detail=detail or None)  # fmt: skip
    if RequestedField.symptoms in fields:
        for p in profile.phenotypes:
            if p.id in t.phenotypes and p.id in labels:
                label = labels[p.id] or p.label
                add(f"symptom:{p.id}", SignupOptionKind.symptom, label,
                    SharedItem(id=p.id, label=label))  # fmt: skip
    if RequestedField.age_range in fields and (rng := age_range(profile)) is not None:
        add("age_range", SignupOptionKind.age_range, f"Age range {rng}", rng)
    if RequestedField.country in fields and profile.country:
        add("country", SignupOptionKind.country, f"Country {profile.country}", profile.country)
    return out


def _shared(chosen: list[tuple[SignupOption, Any]]) -> SharedItems:
    shared = SharedItems()
    lists = {
        SignupOptionKind.diagnosis: shared.diagnoses,
        SignupOptionKind.gene: shared.genes,
        SignupOptionKind.variant: shared.variants,
        SignupOptionKind.symptom: shared.symptoms,
    }
    for option, value in chosen:
        if option.kind == SignupOptionKind.age_range:
            shared.age_range = value
        elif option.kind == SignupOptionKind.country:
            shared.country = value
        else:
            lists[option.kind].append(value)
    return shared


def _recipient(call: Call) -> tuple[str, str]:
    """(card name with the first institution, card name)."""
    card = call.publisher
    name = card.name if card is not None else "the study team"
    inst = card.institutions[0].label if card is not None and card.institutions else None
    return (f"{name}, {inst}" if inst else name), name


# ---- availability and options ---------------------------------------------------------------


async def _existing(db: AsyncSession, user_id: UUID, call_id: UUID) -> Any:
    return (
        (
            await db.execute(
                text(
                    "SELECT id, status FROM call_signups WHERE patient_id = :uid AND call_id = :cid"
                    " AND status IN ('active', 'declined')"
                ),
                {"uid": user_id, "cid": call_id},
            )
        )
        .mappings()
        .first()
    )


async def availability(db: AsyncSession, user: CurrentUser, call: Call) -> SignupAvailability:
    """Whether to offer the sign-up button for this published call (the call stays visible)."""
    if user.role != Role.patient:
        return SignupAvailability(can_sign_up=False, blocked_by=SignupBlock.not_patient)
    own = await db.scalar(
        text("SELECT publisher_id = :uid FROM calls WHERE id = :cid"),
        {"uid": user.id, "cid": call.id},
    )
    if own:
        return SignupAvailability(can_sign_up=False, blocked_by=SignupBlock.own_call)
    existing = await _existing(db, user.id, call.id)
    if existing is not None:
        declined = existing["status"] == SignupStatus.declined
        return SignupAvailability(
            can_sign_up=False,
            blocked_by=SignupBlock.declined if declined else SignupBlock.already_signed_up,
            signup_id=existing["id"],
        )
    if call.adults_only and await connect.age_group(db, user.id) == AgeGroup.minor:
        return SignupAvailability(
            can_sign_up=False, blocked_by=SignupBlock.for_adults, label=FOR_ADULTS_LABEL
        )
    if call.opens_at is not None and call.opens_at > date.today():
        return SignupAvailability(
            can_sign_up=False,
            blocked_by=SignupBlock.not_open_yet,
            label=f"Sign-ups open on {call.opens_at.isoformat()}.",
        )
    return SignupAvailability(can_sign_up=True)


async def _open_call(db: AsyncSession, call_id: UUID) -> Call:
    """The published, open call with its publisher's card, or a clear error."""
    row = (
        (
            await db.execute(
                text("SELECT status, closes_at FROM calls WHERE id = :id AND status = 'published'"),
                {"id": call_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ApiError(404, ErrorCode.not_found, "This call is closed or does not exist.")
    if row["closes_at"] is not None and row["closes_at"] < date.today():
        raise ApiError(
            409,
            ErrorCode.conflict,
            f"This call closed on {row['closes_at'].isoformat()} and takes no more sign-ups.",
        )
    try:
        return await calls_service.get_published(db, call_id)
    except ApiError:  # published and open, but the publisher's card is hidden or unverified
        raise _DB_ERRORS["amber:not_available"] from None


async def options(db: AsyncSession, user: CurrentUser, call_id: UUID) -> SignupOptions:
    """What the sign-up screen offers for this call: the items, the texts and whether to ask
    for the consent, the age group and the guardian checkbox."""
    call = await _open_call(db, call_id)
    group = await connect.age_group(db, user.id)
    consent_ok = await connect.has_current_consent(db, user.id)
    profile = await suggestions.load_profile(db, user.id) if consent_ok else PatientProfile()
    recipient, name = _recipient(call)
    return SignupOptions(
        call_id=call.id,
        call_title=call.title,
        recipient=recipient,
        recipient_name=name,
        options=[option for option, _ in _offer(call, profile).values()],
        authorization_text=AUTHORIZATION_TEXT.replace("{recipient}", recipient).replace(
            "{name}", name
        ),
        consent_active=consent_ok,
        age_group_needed=group is None,
        guardian_required=group == AgeGroup.minor,
        guardian_text=GUARDIAN_TEXT.format(recipient=recipient),
        guardian_text_version=GUARDIAN_TEXT_VERSION,
        about_child=profile.about_child,
        availability=await availability(db, user, call),
    )


# ---- signing up -----------------------------------------------------------------------------


def _availability_error(avail: SignupAvailability) -> ApiError:
    block = avail.blocked_by
    if block == SignupBlock.not_patient:
        return _NOT_PATIENT
    if block == SignupBlock.for_adults:
        return ApiError(403, ErrorCode.forbidden, FOR_ADULTS_LABEL)
    messages = {
        SignupBlock.own_call: "You cannot sign up to your own call.",
        SignupBlock.already_signed_up: "You have already signed up to this call.",
        SignupBlock.declined: "The study team declined your sign-up to this call.",
        SignupBlock.not_open_yet: avail.label or "Sign-ups have not opened yet.",
    }
    return ApiError(409, ErrorCode.conflict, messages.get(block, "Sign-up not possible."))


async def sign_up(
    db: AsyncSession, user: CurrentUser, call_id: UUID, body: SignupRequest
) -> MySignup:
    """Send the ticked items to the call's publisher (see the module docstring)."""
    if user.role != Role.patient:
        raise _NOT_PATIENT
    if not await connect.has_current_consent(db, user.id):
        raise ApiError(403, ErrorCode.consent_required)
    group = await connect.require_age_group(db, user.id)
    call = await _open_call(db, call_id)
    avail = await availability(db, user, call)
    if not avail.can_sign_up:
        raise _availability_error(avail)
    profile = await suggestions.load_profile(db, user.id)
    if profile.about_child and not profile.parental_responsibility_confirmed:
        raise _invalid("parental_responsibility_confirmed")
    guardian_version = None
    if group == AgeGroup.minor:
        if not body.guardian_agreed:
            raise ApiError(403, ErrorCode.guardian_agreement_required)
        guardian_version = GUARDIAN_TEXT_VERSION
    if not body.authorized:
        raise _invalid("authorized")
    if body.authorization_version != AUTHORIZATION_VERSION:
        raise _invalid("authorization_version")
    offered = _offer(call, profile)
    for i, key in enumerate(body.items):
        if key not in offered:
            raise _invalid(f"items.{i}")
    shared = _shared([offered[k] for k in body.items])
    recipient, name = _recipient(call)
    try:
        async with db.begin_nested():
            signup_id = await db.scalar(
                text(
                    "INSERT INTO call_signups (call_id, patient_id, call_title_snapshot,"
                    " recipient_name, display_name, shared, about_child, note,"
                    " authorization_version, guardian_agreed_at, guardian_text_version)"
                    " VALUES (:cid, :uid, :title, :recipient, :name, CAST(:shared AS jsonb),"
                    " :child, :note, :version, CASE WHEN CAST(:gv AS text) IS NOT NULL"
                    " THEN now() END, CAST(:gv AS text)) RETURNING id"
                ),
                {
                    "cid": call.id,
                    "uid": user.id,
                    "title": call.title,
                    "recipient": recipient,
                    "name": body.display_name,
                    "shared": shared.model_dump_json(),
                    "child": profile.about_child,
                    "note": body.note,
                    "version": AUTHORIZATION_VERSION,
                    "gv": guardian_version,
                },
            )
    except DBAPIError as exc:  # the admit trigger's refusals are check violations
        error = _db_error(exc)
        if error is not None:
            raise error from None
        if isinstance(exc, IntegrityError):  # the one-per-call unique index
            raise ApiError(
                409, ErrorCode.conflict, "You have already signed up to this call."
            ) from None
        raise
    if body.open_conversation:
        publisher_id = await db.scalar(
            text("SELECT publisher_id FROM calls WHERE id = :cid"), {"cid": call.id}
        )
        thread_id = await messaging.open_signup_thread(
            db,
            patient_id=user.id,
            publisher_id=publisher_id,
            call_id=call.id,
            signup_id=signup_id,
            patient_name=body.display_name,
            publisher_name=name,
        )
        await db.execute(
            text("UPDATE call_signups SET thread_id = :tid, updated_at = now() WHERE id = :id"),
            {"tid": thread_id, "id": signup_id},
        )
    return await _mine(db, user.id, signup_id)


# ---- the patient's sign-ups -----------------------------------------------------------------


def _shared_items(value: Any) -> SharedItems:
    try:
        return SharedItems.model_validate(value or {})
    except ValueError:
        return SharedItems()


async def _open_call_ids(db: AsyncSession, ids: list[UUID]) -> set[UUID]:
    if not ids:
        return set()
    rows = await db.execute(
        text(
            "SELECT id FROM calls WHERE id = ANY(:ids) AND status = 'published'"
            " AND (closes_at IS NULL OR closes_at >= current_date)"
        ),
        {"ids": ids},
    )
    return {r[0] for r in rows}


def _my(row: Any, open_ids: set[UUID]) -> MySignup:
    return MySignup(
        id=row["id"],
        call_id=row["call_id"],
        call_title=row["call_title_snapshot"],
        call_open=row["call_id"] in open_ids,
        recipient=row["recipient_name"],
        display_name=row["display_name"],
        shared=_shared_items(row["shared"]),
        note=row["note"],
        status=SignupStatus(row["status"]),
        about_child=row["about_child"],
        authorization_version=row["authorization_version"],
        authorized_at=row["authorized_at"],
        guardian_agreed_at=row["guardian_agreed_at"],
        guardian_text_version=row["guardian_text_version"],
        created_at=row["created_at"],
        withdrawn_at=row["withdrawn_at"],
        declined_at=row["declined_at"],
        call_ended_at=row["call_ended_at"],
        delete_after=row["purge_after"],
        thread_id=row["thread_id"],
    )


async def _mine(db: AsyncSession, user_id: UUID, signup_id: UUID) -> MySignup:
    row = (
        (
            await db.execute(
                text(
                    f"SELECT {_COLUMNS} FROM call_signups s WHERE s.id = :id"
                    " AND s.patient_id = :uid"
                ),
                {"id": signup_id, "uid": user_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise _not_found()
    return _my(row, await _open_call_ids(db, [row["call_id"]] if row["call_id"] else []))


async def purge_own(db: AsyncSession, user_id: UUID) -> None:
    """Delete my sign-ups past their time (at read time, like notifications and threads)."""
    await db.execute(_PURGE_OWN_SQL, {"uid": user_id})


async def list_mine(db: AsyncSession, user: CurrentUser) -> MySignupList:
    await purge_own(db, user.id)
    rows = list(
        (
            await db.execute(
                text(
                    f"SELECT {_COLUMNS} FROM call_signups s WHERE s.patient_id = :uid"
                    " ORDER BY s.created_at DESC, s.id"
                ),
                {"uid": user.id},
            )
        ).mappings()
    )
    open_ids = await _open_call_ids(db, [r["call_id"] for r in rows if r["call_id"]])
    return MySignupList(items=[_my(r, open_ids) for r in rows])


async def withdraw(db: AsyncSession, user: CurrentUser, signup_id: UUID) -> None:
    """Withdraw my sign-up: the shared items and the note are deleted at once, the publisher
    keeps a 'withdrew' stub for 30 days, and its conversation closes. Idempotent."""
    thread_id = await db.scalar(
        text(
            "UPDATE call_signups SET status = 'withdrawn', updated_at = now()"
            " WHERE id = :id AND patient_id = :uid AND status IN ('active', 'call_closed')"
            " RETURNING COALESCE(thread_id::text, '')"
        ),
        {"id": signup_id, "uid": user.id},
    )
    if thread_id is None:
        exists = await db.scalar(
            text("SELECT 1 FROM call_signups WHERE id = :id AND patient_id = :uid"),
            {"id": signup_id, "uid": user.id},
        )
        if not exists:
            raise _not_found()
        return
    if thread_id:
        await _close_thread(db, UUID(thread_id))


async def _close_thread(db: AsyncSession, thread_id: UUID) -> None:
    await db.execute(
        text(
            "UPDATE threads SET status = 'closed' WHERE id = :tid"
            " AND status IN ('requested', 'open', 'blocked')"
        ),
        {"tid": thread_id},
    )


# ---- the publisher's view -------------------------------------------------------------------


def _received(row: Any) -> ReceivedSignup:
    minor = row["guardian_text_version"] is not None
    return ReceivedSignup(
        id=row["id"],
        display_name=row["display_name"],
        shared=_shared_items(row["shared"]),
        note=row["note"],
        status=SignupStatus(row["status"]),
        about_child=row["about_child"],
        minor=minor,
        minor_label=MINOR_LABEL if minor else None,
        authorization_version=row["authorization_version"],
        authorized_at=row["authorized_at"],
        created_at=row["created_at"],
        withdrawn_at=row["withdrawn_at"],
        declined_at=row["declined_at"],
        thread_id=row["thread_id"],
    )


async def received(db: AsyncSession, user: CurrentUser, call_id: UUID) -> ReceivedSignupList:
    """The sign-ups to one of my calls (any status of the call), newest first, stubs included,
    nothing past its retention time."""
    call = await calls_service._own_row(db, user, call_id)  # 404 unless it is my call
    rows = (
        await db.execute(
            text(
                f"SELECT {_COLUMNS} FROM call_signups s WHERE s.call_id = :cid AND NOT {_EXPIRED}"
                " ORDER BY s.created_at DESC, s.id"
            ),
            {"cid": call_id},
        )
    ).mappings()
    items = [_received(r) for r in rows]
    return ReceivedSignupList(
        call_id=call_id,
        call_title=call["title"],
        active_count=sum(1 for i in items if i.status == SignupStatus.active),
        max_signups=call["max_signups"],
        items=items,
    )


async def decline(
    db: AsyncSession, user: CurrentUser, call_id: UUID, signup_id: UUID
) -> ReceivedSignup:
    """Decline an active sign-up to my call: its items and note are deleted, a stub stays for
    30 days. Idempotent for a declined one."""
    await calls_service._own_row(db, user, call_id)
    found = await db.scalar(
        text("SELECT 1 FROM call_signups WHERE id = :id AND call_id = :cid"),
        {"id": signup_id, "cid": call_id},
    )
    if not found:
        raise _not_found()
    try:
        async with db.begin_nested():
            await db.execute(text("SELECT decline_call_signup(:id)"), {"id": signup_id})
    except DBAPIError as exc:
        if "amber:not_active" in str(getattr(exc, "orig", "")):
            raise ApiError(
                409, ErrorCode.conflict, "Only active sign-ups can be declined."
            ) from None
        if "amber:not_found" in str(getattr(exc, "orig", "")):
            raise _not_found() from None
        raise
    row = (
        (
            await db.execute(
                text(f"SELECT {_COLUMNS} FROM call_signups s WHERE s.id = :id"), {"id": signup_id}
            )
        )
        .mappings()
        .one()
    )
    return _received(row)


# ---- consent and data rights ----------------------------------------------------------------


async def on_connect_withdrawn(db: AsyncSession, user_id: UUID) -> None:
    """Withdrawal of `connect`: every sign-up is withdrawn (items deleted, the publisher sees a
    'withdrew' stub), suggestions stop and their notifications are deleted. The conversations
    close with the messaging effect."""
    await db.execute(
        text(
            "UPDATE call_signups SET status = 'withdrawn', updated_at = now()"
            " WHERE patient_id = :uid AND status IN ('active', 'call_closed')"
        ),
        {"uid": user_id},
    )
    await suggestions.stop(db, user_id)


async def export(db: AsyncSession, user_id: UUID) -> SignupsExport:
    """My own sign-ups and the suggestions setting (sign-ups to my calls are other people's)."""
    setting = (
        (
            await db.execute(
                text(
                    "SELECT suggestions_enabled, suggestions_enabled_at FROM profiles"
                    " WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
        )
        .mappings()
        .first()
    )
    rows = (
        await db.execute(
            text(
                f"SELECT {_COLUMNS} FROM call_signups s WHERE s.patient_id = :uid"
                " ORDER BY s.created_at, s.id"
            ),
            {"uid": user_id},
        )
    ).mappings()
    return SignupsExport(
        suggestions_enabled=bool(setting and setting["suggestions_enabled"]),
        suggestions_enabled_at=setting["suggestions_enabled_at"] if setting else None,
        signups=[SignupExport(**{**dict(r), "shared": _shared_items(r["shared"])}) for r in rows],
    )
