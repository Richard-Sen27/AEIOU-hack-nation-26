"""Contributions: patient-reported profiles and assets, and user-contributed candidate edges.

Only with an active 'contribute' consent; always pending_review, never promoted automatically,
de-identified (IDs, enums, URLs and short screened text only).
"""

import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.schemas.account import CurrentUser
from backend.schemas.contributions import (
    AssetPayload,
    CandidateEdgePayload,
    Contribution,
    ContributionCreate,
    PhenotypeProfilePayload,
    SharedContribution,
)
from backend.schemas.enums import (
    AgeRange,
    ContributionKind,
    ContributionStatus,
    ErrorCode,
    Origin,
)

log = logging.getLogger(__name__)

MONDO_ID = re.compile(r"^MONDO:\d{7}$")
HP_ID = re.compile(r"^HP:\d{7}$")
NODE_ID = re.compile(r"^(?:[A-Z][A-Za-z_]{1,15}:[A-Za-z0-9_.-]{1,60}|NCT\d{8})$")
SOURCE_REF = re.compile(r"^(?:PMID:\d{1,9}|PMC\d{1,9}|NCT\d{8}|DOI:10\.\d{4,9}/\S{1,200})$")
_LONG_DIGITS = re.compile(r"\d{6,}")
_EMAILISH = re.compile(r"\S@\S")
_PII_ENTITIES = frozenset(
    {
        "PERSON",
        "DATE_OF_BIRTH",
        "STREET_ADDRESS",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "PATIENT_ID",
        "US_SSN",
        "IBAN_CODE",
        "CREDIT_CARD",
        "IP_ADDRESS",
    }
)
MAX_IDS = 100
MAX_DESCRIPTION = 1000


def _invalid(field: str, message: str | None = None) -> ApiError:
    return ApiError(422, ErrorCode.validation_error, message or f"Invalid request fields: {field}")


def _check_ids(values: list[str], pattern: re.Pattern[str], field: str) -> list[str]:
    if len(values) > MAX_IDS:
        raise _invalid(field)
    for i, value in enumerate(values):
        if not pattern.match(value):
            raise _invalid(f"{field}.{i}")
    return list(dict.fromkeys(values))


def check_public_url(value: str | None, field: str) -> None:
    if value is None:
        return
    parts = urlsplit(value)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username
        or parts.password
        or any(c.isspace() for c in value)
    ):
        raise _invalid(field)


async def screen_free_text(value: str | None, field: str, *, max_length: int) -> None:
    """Reject short free text that could identify a person (names, contact data, IDs).

    Regex checks first, then Presidio. Fails closed if the redactor cannot run.
    """
    if value is None:
        return
    message = (
        f"Invalid request fields: {field}. Leave out names, contact details and personal"
        " identifiers."
    )
    if (
        len(value) > max_length
        or _EMAILISH.search(value)
        or _LONG_DIGITS.search(value)
        or "://" in value
    ):
        raise _invalid(field, message)
    if not value.strip():
        raise _invalid(field)
    try:
        from backend.privacy.redaction import redact

        result = await asyncio.to_thread(redact, value)
    except Exception as exc:  # noqa: BLE001 - fail closed, never store unscreened text
        log.error("free-text screening unavailable: %s", type(exc).__name__)
        raise ApiError(500, ErrorCode.internal_error) from None
    if any(span.entity_type in _PII_ENTITIES for span in result.spans):
        raise _invalid(field, message)


async def _validate(body: ContributionCreate) -> tuple[ContributionKind, dict[str, Any]]:
    item = body.root
    payload = item.payload
    if isinstance(payload, PhenotypeProfilePayload):
        if not MONDO_ID.match(payload.disease_id):
            raise _invalid("payload.disease_id")
        present = _check_ids(payload.phenotype_ids, HP_ID, "payload.phenotype_ids")
        absent = _check_ids(payload.excluded_phenotype_ids, HP_ID, "payload.excluded_phenotype_ids")
        if not present or set(present) & set(absent):
            raise _invalid("payload.phenotype_ids")
        if payload.age_range is not None and payload.age_range not in {a.value for a in AgeRange}:
            raise _invalid("payload.age_range")
        payload.phenotype_ids, payload.excluded_phenotype_ids = present, absent
    elif isinstance(payload, AssetPayload):
        await screen_free_text(payload.name, "payload.name", max_length=200)
        await screen_free_text(
            payload.description, "payload.description", max_length=MAX_DESCRIPTION
        )
        check_public_url(payload.url, "payload.url")
        payload.disease_ids = _check_ids(payload.disease_ids, MONDO_ID, "payload.disease_ids")
    elif isinstance(payload, CandidateEdgePayload):
        if not NODE_ID.match(payload.source_id):
            raise _invalid("payload.source_id")
        if not NODE_ID.match(payload.target_id) or payload.target_id == payload.source_id:
            raise _invalid("payload.target_id")
        if payload.source_url is None and payload.source_id_ref is None:
            raise _invalid("payload.source_url")
        check_public_url(payload.source_url, "payload.source_url")
        if payload.source_id_ref is not None and not SOURCE_REF.match(payload.source_id_ref):
            raise _invalid("payload.source_id_ref")
        await screen_free_text(payload.quote, "payload.quote", max_length=500)
    return item.kind, payload.model_dump(mode="json")


def origin_for(kind: ContributionKind | str) -> Origin:
    if ContributionKind(kind) == ContributionKind.candidate_edge:
        return Origin.user_contributed
    return Origin.patient_reported


def contribution_from_row(row: Any) -> Contribution:
    return Contribution(
        id=row["id"],
        kind=ContributionKind(row["kind"]),
        payload=row["payload"] or {},
        status=ContributionStatus(row["status"]),
        origin=origin_for(row["kind"]),
        consent_id=row["consent_id"],
        created_at=row["created_at"],
    )


async def refresh_shared_graph(
    db: AsyncSession, *, contributions: bool = False, flags: bool = False
) -> None:
    """Refresh the graph service's overlays if it offers them; never fails the request."""
    from backend.api.services import graph as graph_service

    names = (["refresh_contributions"] if contributions else []) + (
        ["refresh_flags"] if flags else []
    )
    for name in names:
        fn = getattr(graph_service, name, None)
        if fn is None:
            continue
        try:
            async with db.begin_nested():
                await fn(db)
        except NotImplementedError:
            pass
        except Exception as exc:  # noqa: BLE001 - the write itself succeeded
            log.warning("graph %s failed: %s", name, type(exc).__name__)


_COLUMNS = "id, kind, payload, status, consent_id, created_at"


async def list_own(db: AsyncSession, user: CurrentUser) -> list[Contribution]:
    """The user's contributions, newest first."""
    rows = (
        await db.execute(
            text(
                f"SELECT {_COLUMNS} FROM contributions WHERE user_id = :uid"
                " ORDER BY created_at DESC, id"
            ),
            {"uid": user.id},
        )
    ).mappings()
    return [contribution_from_row(r) for r in rows]


async def create(db: AsyncSession, user: CurrentUser, body: ContributionCreate) -> Contribution:
    """Store a contribution (status pending_review) linked to the active consent."""
    kind, payload = await _validate(body)
    consent_id = await db.scalar(
        text(
            "SELECT id FROM consents WHERE user_id = :uid AND consent_type = 'contribute'"
            " AND revoked_at IS NULL FOR SHARE"
        ),
        {"uid": user.id},
    )
    if consent_id is None:
        raise ApiError(403, ErrorCode.consent_required)
    row = (
        (
            await db.execute(
                text(
                    "INSERT INTO contributions (user_id, kind, payload, status, consent_id)"
                    " VALUES (:uid, :kind, CAST(:payload AS jsonb), :status, :consent)"
                    f" RETURNING {_COLUMNS}"
                ),
                {
                    "uid": user.id,
                    "kind": kind.value,
                    "payload": json.dumps(payload),
                    "status": ContributionStatus.pending_review.value,
                    "consent": consent_id,
                },
            )
        )
        .mappings()
        .one()
    )
    await refresh_shared_graph(db, contributions=True)
    return contribution_from_row(row)


async def delete(db: AsyncSession, user: CurrentUser, contribution_id: UUID) -> None:
    """Delete one of the user's contributions; 404 otherwise (including other users' rows)."""
    deleted = await db.scalar(
        text("DELETE FROM contributions WHERE id = :id AND user_id = :uid RETURNING id"),
        {"id": contribution_id, "uid": user.id},
    )
    if deleted is None:
        raise ApiError(404, ErrorCode.not_found)
    await refresh_shared_graph(db, contributions=True)


async def shared(db: AsyncSession) -> list[SharedContribution]:
    """Contributions visible to all, via shared_contributions() (no user IDs)."""
    rows = (
        await db.execute(
            text("SELECT id, kind, payload, status, created_at FROM shared_contributions()")
        )
    ).mappings()
    return [
        SharedContribution(
            id=r["id"],
            kind=ContributionKind(r["kind"]),
            payload=r["payload"] or {},
            status=ContributionStatus(r["status"]),
            origin=origin_for(r["kind"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]
