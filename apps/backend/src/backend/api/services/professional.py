"""Work details of doctors and researchers: name, institutions, ORCID iD, own atlas entry.

Self-declared and private to the account (contract, Art. 6(1)(b)): never in atlas data, never
sent to a model, never logged, and never shown to other users unless the person verifies their
identity and switches on the public card (api/services/people.py), which shows only the fields
they chose. Linking an atlas entry is not a claim and not a verification.
"""

import json
import re
import unicodedata
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.api.services import auth as auth_service
from backend.api.services.graph import GraphStore, get_graph
from backend.schemas.account import (
    MAX_INSTITUTIONS,
    AtlasEntry,
    AtlasEntryCandidate,
    AtlasMatches,
    AtlasMatchRequest,
    CurrentUser,
    Institution,
    InstitutionInput,
    ProfessionalExport,
    ProfessionalProfile,
    ProfessionalProfileUpdate,
    SuggestedName,
)
from backend.schemas.enums import ErrorCode, NodeType, Relation, Role

PROFESSIONAL_ROLES = frozenset({Role.doctor, Role.researcher})
PERSON_TYPES = frozenset({NodeType.researcher, NodeType.doctor})
MAX_CANDIDATES = 5

_COLUMNS = "first_name, last_name, institutions, orcid_id, atlas_node_id, professional_updated_at"
# Verification and the card rest on the work details: clearing those clears these too.
_VERIFICATION_CLEAR = (
    "role_verified = false, orcid_verified_at = NULL, verified_name = NULL,"
    " verification_method = NULL, verified_at = NULL, verification_reason = NULL,"
    " verification_request = NULL, atlas_link_verified = false, card_visible = false,"
    " card_visible_since = NULL"
)
_CLEAR_SQL = text(
    "UPDATE profiles SET first_name = NULL, last_name = NULL, institutions = '[]'::jsonb,"
    " orcid_id = NULL, atlas_node_id = NULL, professional_updated_at = NULL,"
    f" {_VERIFICATION_CLEAR}, card_id = NULL, card_headline = NULL,"
    " card_show_institutions = true, card_show_atlas_entry = true,"
    " accepts_patient_messages = false, updated_at = now()"
    " WHERE user_id = :uid"
)
_CLEAR_VERIFICATION_SQL = text(
    f"UPDATE profiles SET {_VERIFICATION_CLEAR}, updated_at = now() WHERE user_id = :uid"
)
_EXPORT_COLUMNS = (
    "orcid_verified_at, verified_name, verification_method, verified_at, verification_reason,"
    " verification_request, atlas_link_verified, card_id, card_visible, card_visible_since,"
    " card_headline, card_show_institutions, card_show_atlas_entry, accepts_patient_messages"
)


def require_professional(user: CurrentUser) -> None:
    if user.role not in PROFESSIONAL_ROLES:
        raise ApiError(403, ErrorCode.forbidden, "Work details are for doctors and researchers.")


def _invalid(field: str) -> ApiError:
    return ApiError(422, ErrorCode.validation_error, f"Invalid request fields: {field}")


# ---- name folding (copied from pipeline/extract/common.py; keep in step with it) ------------

_UNICODE_FOLD = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "″": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "−": "-",
        "­": None,  # soft hyphen
        "​": None,  # zero-width space
        "‌": None,
        "‍": None,
        "﻿": None,
    }
)
_WS = re.compile(r"\s+")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value).translate(_UNICODE_FOLD)
    return _WS.sub(" ", value).strip()


def fold(value: str | None) -> str:
    """Lowercase, accent-free, punctuation-free form used for matching names and terms."""
    value = unicodedata.normalize("NFKD", normalize_text(value))
    value = "".join(c for c in value if not unicodedata.combining(c)).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return _WS.sub(" ", value).strip()


def person_name_key(last: str | None, first: str | None) -> str:
    """First given name and last name, folded: the pipeline's `attrs.name_key`."""
    given = fold(first).split()
    return f"{given[0] if given else ''} {fold(last)}".strip()


# ---- prefill ------------------------------------------------------------------------------


def split_name(name: str | None) -> tuple[str | None, str | None]:
    """Last word is the last name, the rest the first name; a single word is a first name."""
    parts = (name or "").split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return " ".join(parts[:-1]), parts[-1]


async def suggested_name(db: AsyncSession, user_id: UUID) -> SuggestedName | None:
    """From the ID token's given/family name, otherwise from `users.name`; never stored."""
    given, family = await auth_service.stored_name_claims(db, user_id)
    row = (
        await db.execute(
            text("SELECT name, auth_provider FROM users WHERE id = :uid"), {"uid": user_id}
        )
    ).first()
    name, provider = (row[0], row[1]) if row else (None, None)
    split_first, split_last = split_name(name)
    first, last = given or split_first, family or split_last
    if first is None and last is None:
        return None
    source = "google" if provider == "google" else "chatgpt"
    return SuggestedName(first_name=first, last_name=last, source=source)


# ---- atlas lookups -------------------------------------------------------------------------


def _node_institutions(store: GraphStore, node_id: str) -> list[Institution]:
    found: dict[str, Institution] = {}
    for eid in store.incident.get(node_id, ()):
        edge = store.edges[eid]
        if edge.relation != Relation.affiliated_with:
            continue
        other = store.nodes.get(edge.target_id if edge.source_id == node_id else edge.source_id)
        if other is not None and other.type == NodeType.institution:
            found.setdefault(other.id, Institution(node_id=other.id, label=other.label))
    return list(found.values())


def _entry(store: GraphStore, node_id: str | None) -> AtlasEntry | None:
    node = store.nodes.get(node_id) if node_id else None
    if node is None or node.type not in PERSON_TYPES:
        return None
    orcid = node.attrs.get("orcid")
    return AtlasEntry(
        node_id=node.id,
        type=node.type,
        label=node.label,
        orcid_id=orcid if isinstance(orcid, str) else None,
        institutions=_node_institutions(store, node.id)[:MAX_INSTITUTIONS],
    )


def _resolve_institutions(store: GraphStore, items: list[InstitutionInput]) -> list[Institution]:
    """Atlas institutions get their label from the atlas; duplicates are dropped."""
    out: list[Institution] = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        if item.node_id is not None:
            node = store.nodes.get(item.node_id)
            if node is None or node.type != NodeType.institution:
                raise _invalid(f"institutions.{i}.node_id")
            resolved = Institution(node_id=node.id, label=node.label)
            key = f"id:{node.id}"
        else:
            resolved = Institution(node_id=None, label=item.label or "")
            key = f"text:{fold(resolved.label)}"
        if key not in seen:
            seen.add(key)
            out.append(resolved)
    return out


# ---- stored values ----------------------------------------------------------------------


def _institutions_from_row(value: Any) -> list[Institution]:
    items = value if isinstance(value, list) else []
    return [Institution.model_validate(i) for i in items if isinstance(i, dict) and i.get("label")]


async def _row(db: AsyncSession, user_id: UUID) -> Any:
    return (
        (
            await db.execute(
                text(f"SELECT {_COLUMNS} FROM profiles WHERE user_id = :uid"), {"uid": user_id}
            )
        )
        .mappings()
        .one()
    )


async def get_professional(db: AsyncSession, user: CurrentUser) -> ProfessionalProfile:
    require_professional(user)
    row = await _row(db, user.id)
    store = get_graph()
    linked = _entry(store, row["atlas_node_id"])
    return ProfessionalProfile(
        first_name=row["first_name"],
        last_name=row["last_name"],
        institutions=_institutions_from_row(row["institutions"]),
        orcid_id=row["orcid_id"],
        atlas_node_id=row["atlas_node_id"],
        linked_entry=linked,
        linked_entry_missing=row["atlas_node_id"] is not None and linked is None,
        updated_at=row["professional_updated_at"],
        suggested=await suggested_name(db, user.id),
    )


async def put_professional(
    db: AsyncSession, user: CurrentUser, body: ProfessionalProfileUpdate
) -> ProfessionalProfile:
    """Replace every work detail. Atlas IDs are checked against the loaded graph."""
    require_professional(user)
    store = get_graph()
    institutions = _resolve_institutions(store, body.institutions)
    if body.atlas_node_id is not None:
        node = store.nodes.get(body.atlas_node_id)
        if node is None or node.type not in PERSON_TYPES:
            raise _invalid("atlas_node_id")
    current = (
        (
            await db.execute(
                text(
                    f"SELECT {_COLUMNS}, orcid_verified_at, atlas_link_verified,"
                    " verification_method FROM profiles WHERE user_id = :uid FOR UPDATE"
                ),
                {"uid": user.id},
            )
        )
        .mappings()
        .one()
    )
    if current["orcid_verified_at"] is not None and body.orcid_id != current["orcid_id"]:
        # A confirmed ORCID iD is locked; deleting the work details removes it.
        raise _invalid("orcid_id")
    inst = [i.model_dump() for i in institutions]
    # A manual review checked the name and institutions: editing them ends the verification.
    reviewed_changed = current["verification_method"] == "institutional_email" and (
        body.first_name != current["first_name"]
        or body.last_name != current["last_name"]
        or inst != [i.model_dump() for i in _institutions_from_row(current["institutions"])]
    )
    await db.execute(
        text(
            "UPDATE profiles SET first_name = :first, last_name = :last,"
            " institutions = CAST(:inst AS jsonb), orcid_id = :orcid, atlas_node_id = :node,"
            " atlas_link_verified = atlas_link_verified AND atlas_node_id IS NOT DISTINCT FROM"
            " CAST(:node AS text),"
            " professional_updated_at = now(), updated_at = now() WHERE user_id = :uid"
        ),
        {
            "uid": user.id,
            "first": body.first_name,
            "last": body.last_name,
            "inst": json.dumps(inst),
            "orcid": body.orcid_id,
            "node": body.atlas_node_id,
        },
    )
    if reviewed_changed:
        await db.execute(_CLEAR_VERIFICATION_SQL, {"uid": user.id})
    await _refresh_cards(db)
    return await get_professional(db, user)


async def _refresh_cards(db: AsyncSession) -> None:
    from backend.api.services.people import refresh_cards

    await refresh_cards(db)


async def clear_professional(db: AsyncSession, user_id: UUID) -> None:
    """Delete every work detail (DELETE /me/professional and the switch to patient), with the
    verification and the public card built on them."""
    await db.execute(_CLEAR_SQL, {"uid": user_id})
    await _refresh_cards(db)


async def clear_verification(db: AsyncSession, user_id: UUID) -> None:
    """End the verification and hide the card (role change between doctor and researcher)."""
    await db.execute(_CLEAR_VERIFICATION_SQL, {"uid": user_id})
    await _refresh_cards(db)


async def export_professional(db: AsyncSession, user_id: UUID) -> ProfessionalExport | None:
    """The stored work details, or None if there are none."""
    row = await _row(db, user_id)
    extra = (
        (
            await db.execute(
                text(f"SELECT {_EXPORT_COLUMNS} FROM profiles WHERE user_id = :uid"),
                {"uid": user_id},
            )
        )
        .mappings()
        .one()
    )
    export = ProfessionalExport(
        first_name=row["first_name"],
        last_name=row["last_name"],
        institutions=_institutions_from_row(row["institutions"]),
        orcid_id=row["orcid_id"],
        atlas_node_id=row["atlas_node_id"],
        updated_at=row["professional_updated_at"],
        **dict(extra),
    )
    return export if export != ProfessionalExport() else None


# ---- matching ------------------------------------------------------------------------------


def find_matches(user: CurrentUser, body: AtlasMatchRequest) -> AtlasMatches:
    """Candidate atlas entries for a draft: exact ORCID iD first, then the same name key
    (institution overlap first). Public node fields only; nothing is stored."""
    require_professional(user)
    store = get_graph()
    wanted = _resolve_institutions(store, body.institutions)
    wanted_ids = {i.node_id for i in wanted if i.node_id}
    wanted_labels = {fold(i.label) for i in wanted} - {""}

    candidates: list[AtlasEntryCandidate] = []
    seen: set[str] = set()

    if body.orcid_id:
        entry = _entry(store, f"ORCID:{body.orcid_id}")
        if entry is not None:
            candidates.append(AtlasEntryCandidate(**entry.model_dump(), matched_by="orcid"))
            seen.add(entry.node_id)

    key = person_name_key(body.last_name, body.first_name)
    if body.first_name and body.last_name and key:
        with_overlap: list[AtlasEntryCandidate] = []
        name_only: list[AtlasEntryCandidate] = []
        for node in store.nodes.values():
            if node.type not in PERSON_TYPES or node.id in seen:
                continue
            if node.attrs.get("name_key") != key:
                continue
            entry = _entry(store, node.id)
            if entry is None:
                continue
            all_institutions = _node_institutions(store, node.id)
            labels = {fold(i.label) for i in all_institutions}
            for attr in ("institutions", "affiliations"):
                raw = node.attrs.get(attr)
                if isinstance(raw, list):
                    labels.update(fold(v) for v in raw if isinstance(v, str))
            overlap = bool(wanted_ids & {i.node_id for i in all_institutions}) or bool(
                wanted_labels & labels
            )
            if overlap:
                with_overlap.append(
                    AtlasEntryCandidate(**entry.model_dump(), matched_by="name_and_institution")
                )
            else:
                name_only.append(AtlasEntryCandidate(**entry.model_dump(), matched_by="name"))
        candidates += sorted(with_overlap, key=lambda c: c.node_id)
        candidates += sorted(name_only, key=lambda c: c.node_id)

    return AtlasMatches(candidates=candidates[:MAX_CANDIDATES])
