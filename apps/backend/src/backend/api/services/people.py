"""Verified doctors and researchers with an opt-in public card ("Reachable in Amber").

Contract basis (Art. 6(1)(b)): the card is the person's own switch, off by default. Other users
see a card only through the SECURITY DEFINER function professional_cards(), which returns rows
only for doctors and researchers with `role_verified AND card_visible`, and only the fields the
person chose to show. The API caches its result in memory and refreshes it after every change in
this process; changes from elsewhere (the operator CLI, another worker) show within
CACHE_MAX_AGE_S. A single card (`GET /people/{card_id}`) is always read fresh.

Professionals get no API that returns patient rows or counts: cards are about professionals only.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.api.services import orcid
from backend.api.services.graph import GraphStore, get_graph, get_node
from backend.api.services.professional import PERSON_TYPES, PROFESSIONAL_ROLES
from backend.config import get_settings
from backend.schemas.account import CurrentUser
from backend.schemas.atlas import AtlasSummary, SummarySectionKey
from backend.schemas.enums import ErrorCode, NodeType, Role
from backend.schemas.people import (
    SIMULATED_METHODS,
    VERIFICATION_LABELS,
    CardInstitution,
    CardSettings,
    CardSettingsUpdate,
    CardVerification,
    MyCard,
    OrcidStart,
    OrcidStartRequest,
    PeopleList,
    PublicCard,
    VerificationRequestCreate,
    VerificationRequestState,
    VerificationState,
)

log = logging.getLogger(__name__)

CACHE_MAX_AGE_S = 60.0
DEFAULT_RETURN = "/profile"
_CARD_COLUMNS = (
    "card_id, role, name, name_verified, institutions, orcid_id, atlas_node_id, headline,"
    " accepts_patient_messages, verification_method"
)
_OWN_COLUMNS = (
    "role, role_verified, first_name, last_name, institutions, orcid_id, atlas_node_id,"
    " orcid_verified_at, verified_name, verification_method, verified_at, verification_request,"
    " atlas_link_verified, card_id, card_visible, card_visible_since, card_headline,"
    " card_show_institutions, card_show_atlas_entry, accepts_patient_messages"
)
_PEOPLE_SECTIONS = (SummarySectionKey.researchers, SummarySectionKey.doctors)


# ---- card rows -> public cards -------------------------------------------------------------


def _institutions(value: Any) -> list[CardInstitution]:
    if isinstance(value, str):
        value = json.loads(value)
    items = value if isinstance(value, list) else []
    return [
        CardInstitution(node_id=i.get("node_id"), label=i["label"])
        for i in items[:3]
        if isinstance(i, dict) and i.get("label")
    ]


def _name_source(method: str, name_verified: bool) -> str:
    if not name_verified or method == "manual_simulated":
        return "self_declared"
    return "reviewed" if method == "institutional_email" else "orcid"


def card_from_row(row: Any) -> PublicCard:
    """A professional_cards() row (or the same shape built from the owner's row)."""
    method = row["verification_method"]
    node = get_node(row["atlas_node_id"]) if row["atlas_node_id"] else None
    return PublicCard(
        card_id=row["card_id"],
        role=Role(row["role"]),
        name=row["name"],
        name_source=_name_source(method, row["name_verified"]),
        institutions=_institutions(row["institutions"]),
        orcid_id=row["orcid_id"],
        orcid_url=f"https://orcid.org/{row['orcid_id']}" if row["orcid_id"] else None,
        atlas_node_id=row["atlas_node_id"],
        atlas_node_label=node.label if node is not None else None,
        headline=row["headline"],
        accepts_patient_messages=row["accepts_patient_messages"],
        verification=CardVerification(
            method=method,
            label=VERIFICATION_LABELS[method],
            simulated=method in SIMULATED_METHODS,
        ),
    )


# ---- in-memory cache ---------------------------------------------------------------------


@dataclass
class _Cache:
    loaded_at: float = 0.0
    cards: dict[UUID, PublicCard] = field(default_factory=dict)
    by_node: dict[str, UUID] = field(default_factory=dict)
    graph_key: tuple[int, str | None] | None = None
    by_disease: dict[str, list[UUID]] = field(default_factory=dict)


_cache = _Cache()


async def refresh_cards(db: AsyncSession) -> None:
    """Re-read professional_cards() into memory; never fails the request that changed a card."""
    global _cache
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(text(f"SELECT {_CARD_COLUMNS} FROM professional_cards()"))
            ).mappings()
            cards = {r["card_id"]: card_from_row(r) for r in rows}
    except Exception as exc:  # noqa: BLE001 - the write itself succeeded
        log.warning("card cache refresh failed: %s", type(exc).__name__)
        _cache = _Cache()  # empty and stale: the next read retries
        return
    _cache = _Cache(
        loaded_at=time.monotonic(),
        cards=cards,
        by_node={c.atlas_node_id: c.card_id for c in cards.values() if c.atlas_node_id},
    )


async def _current(db: AsyncSession) -> _Cache:
    if time.monotonic() - _cache.loaded_at > CACHE_MAX_AGE_S:
        await refresh_cards(db)
    return _cache


def _person_diseases(store: GraphStore, node_id: str) -> set[str]:
    """Diseases the atlas links to a researcher or doctor entry: direct edges plus the summary
    chains (papers, grants, trials) that end in a disease."""
    from backend.api.services.atlas_summary import CHAINS, _Adjacency, _walk

    node = get_node(node_id)
    if node is None or node.type not in PERSON_TYPES:
        return set()
    adj = _Adjacency(store)
    out = {other.id for _edge, other in adj(node.id) if other.type == NodeType.disease}
    for chain in CHAINS.get(node.type, ()):
        if NodeType.disease not in chain.steps[-1].types:
            continue
        for _edges, nodes in _walk(node, chain, adj):
            if nodes[-1].type == NodeType.disease:
                out.add(nodes[-1].id)
    return out


def _disease_index(cache: _Cache) -> dict[str, list[UUID]]:
    store = get_graph()
    key = (id(store), store.data_version)
    if cache.graph_key != key:
        index: dict[str, list[UUID]] = {}
        for node_id, card_id in cache.by_node.items():
            for disease_id in _person_diseases(store, node_id):
                index.setdefault(disease_id, []).append(card_id)
        cache.by_disease, cache.graph_key = index, key
    return cache.by_disease


# ---- reading cards (signed-in users) -------------------------------------------------------


async def get_card(db: AsyncSession, card_id: UUID) -> PublicCard:
    row = (
        (
            await db.execute(
                text(f"SELECT {_CARD_COLUMNS} FROM professional_cards() WHERE card_id = :id"),
                {"id": card_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ApiError(404, ErrorCode.not_found)
    return card_from_row(row)


async def list_people(db: AsyncSession, disease_id: str) -> PeopleList:
    node = get_node(disease_id)
    if node is None or node.type != NodeType.disease:
        raise ApiError(404, ErrorCode.not_found)
    cache = await _current(db)
    ids = _disease_index(cache).get(disease_id, [])
    items = sorted(
        (cache.cards[i] for i in ids if i in cache.cards),
        key=lambda c: (c.name.casefold(), str(c.card_id)),
    )
    return PeopleList(disease_id=disease_id, items=items)


async def attach_card_ids(db: AsyncSession, summary: AtlasSummary) -> AtlasSummary:
    """Mark researcher and doctor items that have a visible, verified card linked by a verified
    atlas entry. Only for signed-in users (the route decides)."""
    cache = await _current(db)
    if not cache.by_node:
        return summary
    for section in summary.sections:
        if section.key in _PEOPLE_SECTIONS:
            for item in section.items:
                item.card_id = cache.by_node.get(item.id)
    return summary


# ---- own card ----------------------------------------------------------------------------


async def _own(db: AsyncSession, user_id: UUID) -> Any:
    return (
        (
            await db.execute(
                text(f"SELECT {_OWN_COLUMNS} FROM profiles WHERE user_id = :uid FOR UPDATE"),
                {"uid": user_id},
            )
        )
        .mappings()
        .one()
    )


def _own_name(row: Any) -> str | None:
    if row["verified_name"]:
        return row["verified_name"]
    name = " ".join(p for p in (row["first_name"], row["last_name"]) if p)
    return name or None


def _blocked(row: Any) -> str | None:
    if row["role"] not in {r.value for r in PROFESSIONAL_ROLES}:
        return "role"
    if not row["role_verified"] or not row["verification_method"]:
        return "not_verified"
    if _own_name(row) is None:
        return "no_name"
    return None


def _preview(row: Any, card_id: UUID) -> PublicCard:
    """The card exactly as professional_cards() would return it (same rules, own row)."""
    return card_from_row(
        {
            "card_id": card_id,
            "role": row["role"],
            "name": _own_name(row),
            "name_verified": bool(row["verified_name"]),
            "institutions": row["institutions"] if row["card_show_institutions"] else [],
            "orcid_id": row["orcid_id"] if row["orcid_verified_at"] else None,
            "atlas_node_id": (
                row["atlas_node_id"]
                if row["atlas_link_verified"] and row["card_show_atlas_entry"]
                else None
            ),
            "headline": row["card_headline"],
            "accepts_patient_messages": row["accepts_patient_messages"],
            "verification_method": row["verification_method"],
        }
    )


def _request_state(value: Any) -> VerificationRequestState | None:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict) or value.get("status") not in ("pending", "rejected"):
        return None
    pending = value["status"] == "pending"
    return VerificationRequestState(
        status=value["status"],
        requested_at=value["requested_at"],
        decided_at=value.get("decided_at"),
        institutional_email=value.get("institutional_email") if pending else None,
        profile_url=value.get("profile_url") if pending else None,
    )


def _my_card(row: Any) -> MyCard:
    method = row["verification_method"] if row["role_verified"] else None
    blocked = _blocked(row)
    return MyCard(
        verification=VerificationState(
            verified=bool(row["role_verified"] and method),
            method=method,
            label=VERIFICATION_LABELS.get(method) if method else None,
            simulated=method in SIMULATED_METHODS,
            verified_at=row["verified_at"] if method else None,
            orcid_id_confirmed=row["orcid_verified_at"] is not None,
            atlas_link_verified=row["atlas_link_verified"],
            request=_request_state(row["verification_request"]),
            orcid_available=orcid.mode() is not None,
            orcid_simulated=orcid.mode() == "mock",
            request_auto_approved=auto_verify_enabled(),
        ),
        settings=CardSettings(
            visible=row["card_visible"] and blocked is None,
            visible_since=row["card_visible_since"] if row["card_visible"] else None,
            headline=row["card_headline"],
            accepts_patient_messages=row["accepts_patient_messages"],
            show_institutions=row["card_show_institutions"],
            show_atlas_entry=row["card_show_atlas_entry"],
        ),
        card_id=row["card_id"],
        can_show=blocked is None,
        blocked_reason=blocked,
        preview=_preview(row, row["card_id"] or uuid4()) if blocked is None else None,
    )


async def get_my_card(db: AsyncSession, user: CurrentUser) -> MyCard:
    return _my_card(await _own(db, user.id))


async def put_my_card(db: AsyncSession, user: CurrentUser, body: CardSettingsUpdate) -> MyCard:
    """Replace the card settings. Switching on needs a verified doctor or researcher with a name;
    switching off works for everyone and removes the card at once."""
    row = await _own(db, user.id)
    if body.visible:
        blocked = _blocked(row)
        if blocked == "role":
            raise ApiError(403, ErrorCode.forbidden, "Cards are for doctors and researchers.")
        if blocked == "not_verified":
            raise ApiError(409, ErrorCode.conflict, "Confirm your identity first.")
        if blocked == "no_name":
            raise ApiError(409, ErrorCode.conflict, "Add your name in your work details first.")
    await db.execute(
        text(
            "UPDATE profiles SET card_id = CASE WHEN :visible THEN COALESCE(card_id, :new_id)"
            " ELSE card_id END,"
            " card_visible_since = CASE WHEN :visible AND NOT card_visible THEN now()"
            " WHEN :visible THEN card_visible_since END,"
            " card_visible = :visible, card_headline = :headline,"
            " accepts_patient_messages = :accepts, card_show_institutions = :show_inst,"
            " card_show_atlas_entry = :show_atlas, updated_at = now() WHERE user_id = :uid"
        ),
        {
            "uid": user.id,
            "visible": body.visible,
            "new_id": uuid4(),
            "headline": body.headline,
            "accepts": body.accepts_patient_messages,
            "show_inst": body.show_institutions,
            "show_atlas": body.show_atlas_entry,
        },
    )
    await refresh_cards(db)
    return await get_my_card(db, user)


# ---- manual verification request -------------------------------------------------------------


def auto_verify_enabled() -> bool:
    """Manual requests are approved at once as 'manual_simulated' (demo only)."""
    return orcid.mock_enabled() or get_settings().demo_auto_verify


async def request_verification(
    db: AsyncSession, user: CurrentUser, body: VerificationRequestCreate
) -> MyCard:
    """Store a manual review request; the operator decides with `backend verify-professional`."""
    if user.role not in PROFESSIONAL_ROLES:
        raise ApiError(403, ErrorCode.forbidden, "Verification is for doctors and researchers.")
    row = await _own(db, user.id)
    if row["role_verified"] and row["verification_method"]:
        raise ApiError(409, ErrorCode.conflict, "Your identity is already confirmed.")
    request = {
        "status": "pending",
        "institutional_email": body.institutional_email,
        "profile_url": body.profile_url,
        "requested_at": datetime.now(UTC).isoformat(),
    }
    if auto_verify_enabled():
        # Local demo (ORCID_MOCK on, loopback) or hosted demo (DEMO_AUTO_VERIFY): approve at
        # once, labelled as simulated. The e-mail and link are not kept. Otherwise the request
        # waits for the operator.
        await db.execute(
            text(
                "UPDATE profiles SET role_verified = true,"
                " verification_method = 'manual_simulated', verified_at = now(),"
                " verification_reason = 'demo: approved automatically',"
                " verification_request = NULL, updated_at = now() WHERE user_id = :uid"
            ),
            {"uid": user.id},
        )
        await refresh_cards(db)
        return await get_my_card(db, user)
    await db.execute(
        text(
            "UPDATE profiles SET verification_request = CAST(:req AS jsonb), updated_at = now()"
            " WHERE user_id = :uid"
        ),
        {"uid": user.id, "req": json.dumps(request)},
    )
    return await get_my_card(db, user)


async def withdraw_verification_request(db: AsyncSession, user: CurrentUser) -> None:
    await db.execute(
        text(
            "UPDATE profiles SET verification_request = NULL, updated_at = now()"
            " WHERE user_id = :uid"
        ),
        {"uid": user.id},
    )


# ---- ORCID confirmation --------------------------------------------------------------------


def _safe_return_to(value: str | None) -> str:
    from backend.api.services.auth import safe_return_to

    path = safe_return_to(value)
    return DEFAULT_RETURN if path == "/" and not value else path


def _back(return_to: str, result: str) -> RedirectResponse:
    base = get_settings().frontend_url.rstrip("/")
    sep = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{base}{return_to}{sep}{urlencode({'orcid': result})}", 302)


async def start_orcid(db: AsyncSession, user: CurrentUser, body: OrcidStartRequest) -> OrcidStart:
    if user.role not in PROFESSIONAL_ROLES:
        raise ApiError(
            403, ErrorCode.forbidden, "ORCID confirmation is for doctors and researchers."
        )
    current = orcid.mode()
    if current is None:
        raise ApiError(501, ErrorCode.not_implemented, "ORCID sign-in is not configured.")
    simulated = current == "mock"
    state = orcid.make_state(user.id, _safe_return_to(body.return_to), simulated)
    hint = None
    if simulated:
        hint = await db.scalar(
            text("SELECT orcid_id FROM profiles WHERE user_id = :uid"), {"uid": user.id}
        )
    return OrcidStart(authorize_url=orcid.authorize_url(state, hint), simulated=simulated)


async def orcid_callback(
    request: Request, db: AsyncSession, user: CurrentUser | None
) -> RedirectResponse:
    """Finish ORCID sign-in. Redirects to the frontend with ?orcid=confirmed, denied, failed or
    already_linked (the iD is confirmed on another account)."""
    q = request.query_params
    if user is None:
        return _back(DEFAULT_RETURN, "failed")
    claims = orcid.read_state(q.get("state"), user.id)
    if claims is None:
        return _back(DEFAULT_RETURN, "failed")
    return_to = _safe_return_to(claims.get("rt"))
    if q.get("error"):
        return _back(return_to, "denied")
    if user.role not in PROFESSIONAL_ROLES:
        return _back(return_to, "failed")
    try:
        identity = await orcid.exchange(q.get("code"), simulated=bool(claims.get("sim")))
    except orcid.OrcidError:
        return _back(return_to, "failed")
    linked = get_node(f"ORCID:{identity.orcid_id}")
    node_id = linked.id if linked is not None and linked.type in PERSON_TYPES else None
    try:
        async with db.begin_nested():
            await db.execute(
                text(
                    "UPDATE profiles SET orcid_id = :orcid, orcid_verified_at = now(),"
                    " verified_name = :name, role_verified = true, verification_method = :method,"
                    " verified_at = now(), verification_reason = NULL,"
                    " verification_request = NULL,"
                    " atlas_node_id = COALESCE(CAST(:node AS text), atlas_node_id),"
                    " atlas_link_verified = CAST(:node AS text) IS NOT NULL,"
                    " professional_updated_at = now(), updated_at = now()"
                    " WHERE user_id = :uid AND role IN ('doctor', 'researcher')"
                ),
                {
                    "uid": user.id,
                    "orcid": identity.orcid_id,
                    "name": identity.name,
                    "method": "orcid_simulated" if identity.simulated else "orcid",
                    "node": node_id,
                },
            )
    except IntegrityError:
        return _back(return_to, "already_linked")
    await refresh_cards(db)
    return _back(return_to, "confirmed")
