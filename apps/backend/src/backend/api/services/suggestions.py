"""Suggestions of calls (connect stage 4): published calls that overlap the patient's profile.

Held under the `connect` consent plus the user's own switch `suggestions_enabled` (off by
default). Computed per request in the patient's own transaction: the inputs are the patient's
confirmed, non-excluded profile items (owner-only table) and the published calls (readable by
every signed-in user). Nothing is stored except `call_match` rows in the patient's own
notifications table; publishers have no way to learn who was suggested, and nothing about
suggestions is logged.

Reasons and score: an exact disease of the profile among the call's diseases (strong, 3); a gene
of the profile, or the gene of a profile variant, among the call's genes (2); at least two exact
HPO ids of the profile among the call's symptoms (1). Age and country are returned as
information and never hide a suggestion. Suggestions gate nothing: every published call is
listed for every signed-in user and sign-ups do not depend on them.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.api.services import calls as calls_service
from backend.api.services import connect
from backend.schemas.account import CurrentUser
from backend.schemas.calls import AtlasRef, Call
from backend.schemas.enums import AgeRange, ErrorCode
from backend.schemas.profile import PatientProfile
from backend.schemas.signups import (
    SUGGESTION_SENTENCE,
    SuggestedCall,
    SuggestionList,
    SuggestionReason,
    SuggestionReasonKind,
    SuggestionSettings,
)

CALL_MATCH = "call_match"
MIN_SYMPTOMS = 2
WEIGHTS = {
    SuggestionReasonKind.disease: 3,
    SuggestionReasonKind.gene: 2,
    SuggestionReasonKind.symptoms: 1,
}
AGE_BOUNDS: dict[AgeRange, tuple[int, int]] = {
    AgeRange.under_1: (0, 1),
    AgeRange.age_1_5: (1, 5),
    AgeRange.age_6_12: (6, 12),
    AgeRange.age_13_17: (13, 17),
    AgeRange.age_18_39: (18, 39),
    AgeRange.age_40_64: (40, 64),
    AgeRange.age_65_plus: (65, 120),
}
_FILL_CACHE_MAX = 50_000

# user id -> the marker the user's call_match notifications were last filled for (per process).
_filled: dict[UUID, tuple[Any, ...]] = {}


@dataclass
class ProfileTargets:
    """The confirmed, non-excluded items of a profile that matching may use."""

    diseases: set[str] = field(default_factory=set)
    genes: set[str] = field(default_factory=set)
    variant_genes: set[str] = field(default_factory=set)
    phenotypes: set[str] = field(default_factory=set)


def targets(profile: PatientProfile) -> ProfileTargets:
    return ProfileTargets(
        diseases={d.id for d in profile.diseases if d.confirmed_at is not None},
        genes={g.id for g in profile.genes if g.confirmed_at is not None},
        variant_genes={
            v.gene_id for v in profile.variants if v.confirmed_at is not None and v.gene_id
        },
        phenotypes={
            p.id for p in profile.phenotypes if p.confirmed_at is not None and not p.excluded
        },
    )


def _pick(refs: list[AtlasRef], ids: set[str]) -> list[AtlasRef]:
    return [r for r in refs if r.id in ids]


def reasons_for(call: Call, t: ProfileTargets) -> list[SuggestionReason]:
    out: list[SuggestionReason] = []
    diseases = _pick(call.diseases, t.diseases)
    if diseases:
        out.append(SuggestionReason(kind=SuggestionReasonKind.disease, items=diseases))
    genes = _pick(call.genes, t.genes | t.variant_genes)
    if genes:
        via_variant = any(g.id in t.variant_genes and g.id not in t.genes for g in genes)
        out.append(
            SuggestionReason(kind=SuggestionReasonKind.gene, items=genes, via_variant=via_variant)
        )
    symptoms = _pick(call.phenotypes, t.phenotypes)
    if len(symptoms) >= MIN_SYMPTOMS:
        out.append(SuggestionReason(kind=SuggestionReasonKind.symptoms, items=symptoms))
    return out


def _label(ref: AtlasRef) -> str:
    return ref.label or ref.id


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def sentence(reasons: list[SuggestionReason]) -> str:
    parts: list[str] = []
    for reason in reasons:
        if reason.kind == SuggestionReasonKind.symptoms:
            parts.append("the symptoms " + _join([_label(r) for r in reason.items]))
        else:
            parts.extend(_label(r) for r in reason.items)
    return SUGGESTION_SENTENCE.format(reasons=_join(parts))


def age_fits(call: Call, profile: PatientProfile) -> bool | None:
    if call.min_age is None and call.max_age is None:
        return None
    low_call = call.min_age if call.min_age is not None else 0
    high_call = call.max_age if call.max_age is not None else 120
    if profile.age_years is not None:
        return low_call <= profile.age_years <= high_call
    if profile.age_range is not None:
        low, high = AGE_BOUNDS[profile.age_range]
        return low <= high_call and high >= low_call
    return None


def country_listed(call: Call, profile: PatientProfile) -> bool | None:
    if not profile.country or not call.countries:
        return None
    return profile.country in call.countries


async def load_profile(db: AsyncSession, user_id: UUID) -> PatientProfile:
    """The stored profile (empty when none or unreadable); the user's own row under RLS."""
    data = await db.scalar(
        text("SELECT profile FROM patient_profiles WHERE user_id = :uid"), {"uid": user_id}
    )
    try:
        return PatientProfile.model_validate({**(data or {}), "updated_at": None})
    except ValueError:
        return PatientProfile()


# ---- settings -------------------------------------------------------------------------------


async def _setting(db: AsyncSession, user_id: UUID) -> Any:
    return (
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


async def active(db: AsyncSession, user_id: UUID) -> tuple[bool, bool]:
    """(consent of the current text active, switched on)."""
    row = await _setting(db, user_id)
    enabled = bool(row and row["suggestions_enabled"])
    return await connect.has_current_consent(db, user_id), enabled


async def get_settings(db: AsyncSession, user: CurrentUser) -> SuggestionSettings:
    row = await _setting(db, user.id)
    return SuggestionSettings(
        enabled=bool(row and row["suggestions_enabled"]),
        enabled_at=row["suggestions_enabled_at"] if row else None,
        consent_active=await connect.has_current_consent(db, user.id),
    )


async def set_enabled(db: AsyncSession, user: CurrentUser, enabled: bool) -> SuggestionSettings:
    """Switch suggestions on (needs the current connect consent) or off (deletes call_match
    notifications)."""
    if enabled and not await connect.has_current_consent(db, user.id):
        raise ApiError(403, ErrorCode.consent_required)
    await db.execute(
        text(
            "UPDATE profiles SET suggestions_enabled = :on, suggestions_enabled_at = CASE"
            " WHEN :on THEN COALESCE(suggestions_enabled_at, now()) END, updated_at = now()"
            " WHERE user_id = :uid"
        ),
        {"uid": user.id, "on": enabled},
    )
    if not enabled:
        await stop(db, user.id)
    return await get_settings(db, user)


async def stop(db: AsyncSession, user_id: UUID) -> None:
    """Switch suggestions off and delete their notifications (switch-off, consent withdrawal)."""
    await db.execute(
        text(
            "UPDATE profiles SET suggestions_enabled = false, suggestions_enabled_at = NULL"
            " WHERE user_id = :uid AND suggestions_enabled"
        ),
        {"uid": user_id},
    )
    await delete_notifications(db, user_id)


async def delete_notifications(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(
        text("DELETE FROM notifications WHERE user_id = :uid AND kind = :k"),
        {"uid": user_id, "k": CALL_MATCH},
    )
    _filled.pop(user_id, None)


# ---- matching -------------------------------------------------------------------------------


async def _matches(
    db: AsyncSession, user_id: UUID, profile: PatientProfile
) -> list[tuple[Call, list[SuggestionReason]]]:
    t = targets(profile)
    if not (t.diseases or t.genes or t.variant_genes or len(t.phenotypes) >= MIN_SYMPTOMS):
        return []
    found = []
    for call in (await calls_service.list_published(db, None)).items:
        reasons = reasons_for(call, t)
        if reasons:
            found.append((call, reasons))
    return found


def _score(reasons: list[SuggestionReason]) -> int:
    return sum(WEIGHTS[r.kind] for r in reasons)


async def suggested(db: AsyncSession, user: CurrentUser) -> SuggestionList:
    from backend.api.services import signups  # signups imports this module

    consent_ok, enabled = await active(db, user.id)
    if not (consent_ok and enabled):
        return SuggestionList(consent_active=consent_ok, enabled=enabled, items=[])
    profile = await load_profile(db, user.id)
    items = []
    for call, reasons in await _matches(db, user.id, profile):
        items.append(
            SuggestedCall(
                call=call,
                score=_score(reasons),
                reasons=reasons,
                sentence=sentence(reasons),
                age_fits=age_fits(call, profile),
                country_listed=country_listed(call, profile),
                signup=await signups.availability(db, user, call),
            )
        )
    items.sort(key=lambda s: -s.score)  # stable: published calls come newest first
    return SuggestionList(consent_active=True, enabled=True, items=items)


# ---- call_match notifications (filled lazily with the stage 1 notifications) ----------------

_MARKER_SQL = text(
    "SELECT max(published_at), count(*),"
    " (SELECT updated_at FROM patient_profiles WHERE user_id = :uid)"
    " FROM calls WHERE status = 'published'"
)


async def fill_notifications(db: AsyncSession, user_id: UUID, *, force: bool) -> None:
    """Insert a `call_match` notification (in the user's own table) for each matching published
    call not notified before. Runs only with the current connect consent and the switch on;
    gated per process by a marker (published calls and the profile's update time)."""
    consent_ok, enabled = await active(db, user_id)
    if not (consent_ok and enabled):
        return
    marker = tuple((await db.execute(_MARKER_SQL, {"uid": user_id})).one())
    if not force and _filled.get(user_id) == marker:
        return
    profile = await load_profile(db, user_id)
    for call, reasons in await _matches(db, user_id, profile):
        disease = next((r.items[0].id for r in reasons if r.kind.value == "disease"), None)
        await db.execute(
            text(
                "INSERT INTO notifications (user_id, kind, ref_id, subject_node_id, dedupe_key)"
                " VALUES (:uid, :k, :ref, :disease, :key)"
                " ON CONFLICT (user_id, dedupe_key) DO NOTHING"
            ),
            {
                "uid": user_id,
                "k": CALL_MATCH,
                "ref": str(call.id),
                "disease": disease,
                "key": f"call|{call.id}",
            },
        )
    if len(_filled) >= _FILL_CACHE_MAX:
        _filled.clear()
    _filled[user_id] = marker
