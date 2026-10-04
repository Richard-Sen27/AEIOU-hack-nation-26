"""Followed diseases and in-app notifications about them.

Everything here runs in the signed-in user's own transaction under row-level security: follows
and notifications are owner-only tables, and the only other input is the public graph
(`graph_changes` and the in-memory graph store). Nothing about one user is visible to another.

Notifications are filled lazily when the user reads the list or the unread count: new
`graph_changes` rows for followed diseases, from loads after the follow started, that are not
yet a notification (unique dedupe key). No text is stored; labels come from the current graph
when read. The unread count fills at most once per change marker (the newest `graph_changes`
row) per user and process, so the once-a-minute poll is two cheap queries.
"""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.api.services.atlas_tree import is_focus
from backend.api.services.graph import get_graph
from backend.schemas.account import CurrentUser
from backend.schemas.enums import ErrorCode, NodeType
from backend.schemas.follows import (
    MAX_FOLLOWS,
    Follow,
    FollowExport,
    FollowFromProfileResult,
    FollowList,
    MarkRead,
    Notification,
    NotificationExport,
    NotificationKind,
    NotificationList,
    UnreadCount,
)

RETENTION_DAYS = 90
GRAPH_KINDS = tuple(k.value for k in NotificationKind)
_MONDO = re.compile(r"^MONDO:\d{7}$")
_NCT = re.compile(r"^NCT\d{8}$")
_FILL_CACHE_MAX = 50_000

# user id -> the change marker the user's notifications were last filled for (per process).
_filled: dict[UUID, datetime | None] = {}

_PURGE_SQL = text(
    "DELETE FROM notifications WHERE user_id = :uid"
    f" AND created_at < now() - interval '{RETENTION_DAYS} days'"
)
_MARKER_SQL = text("SELECT max(created_at) FROM graph_changes")
# Changes from loads after the follow started: newer than the follow and not of the version
# that was live when the user followed (that content was already in the atlas then).
_FILL_SQL = text(
    """
    INSERT INTO notifications (user_id, kind, ref_id, subject_node_id, data_version, dedupe_key)
    SELECT f.user_id, gc.change, gc.node_id, gc.disease_id, gc.data_version,
           concat_ws('|', 'graph', gc.data_version, gc.disease_id, gc.node_id, gc.change)
      FROM follows f
      JOIN graph_changes gc ON gc.disease_id = f.node_id
     WHERE f.user_id = :uid
       AND gc.created_at > f.created_at
       AND gc.data_version IS DISTINCT FROM f.since_version
       AND gc.change IN ('added', 'now_recruiting')
    ON CONFLICT (user_id, dedupe_key) DO NOTHING
    """
)
_UNREAD_SQL = text(
    "SELECT count(*) FROM notifications WHERE user_id = :uid AND read_at IS NULL"
    f" AND kind IN ('added', 'now_recruiting', 'call_match')"
    f" AND created_at >= now() - interval '{RETENTION_DAYS} days'"
)


# ---- follows ------------------------------------------------------------------------------


async def _data_version(db: AsyncSession) -> str | None:
    version = get_graph().data_version
    if version:
        return version
    return await db.scalar(
        text("SELECT data_version FROM ingestion_runs ORDER BY created_at DESC LIMIT 1")
    )


def atlas_disease(node_id: str) -> Any:
    """The disease node in the current atlas, or None."""
    node = get_graph().nodes.get(node_id) if _MONDO.match(node_id) else None
    return node if node is not None and node.type == NodeType.disease else None


def _follow(row: Any) -> Follow:
    node = atlas_disease(row["node_id"])
    return Follow(
        node_id=row["node_id"],
        label=node.label if node is not None else None,
        in_atlas=node is not None,
        updates_available=node is not None and is_focus(node),
        created_at=row["created_at"],
        since_version=row["since_version"],
    )


async def list_follows(db: AsyncSession, user: CurrentUser) -> FollowList:
    rows = (
        await db.execute(
            text(
                "SELECT node_id, created_at, since_version FROM follows WHERE user_id = :uid"
                " ORDER BY created_at DESC, node_id"
            ),
            {"uid": user.id},
        )
    ).mappings()
    return FollowList(items=[_follow(r) for r in rows], limit=MAX_FOLLOWS)


async def _lock_user(db: AsyncSession, user_id: UUID) -> None:
    """Serialize follow writes per user so the limit holds under concurrent requests."""
    await db.execute(
        text("SELECT 1 FROM profiles WHERE user_id = :uid FOR UPDATE"), {"uid": user_id}
    )


async def _followed_ids(db: AsyncSession, user_id: UUID) -> set[str]:
    rows = await db.execute(
        text("SELECT node_id FROM follows WHERE user_id = :uid"), {"uid": user_id}
    )
    return {r[0] for r in rows}


async def _insert(db: AsyncSession, user_id: UUID, node_id: str, version: str | None) -> Follow:
    row = (
        (
            await db.execute(
                text(
                    "INSERT INTO follows (user_id, node_id, since_version)"
                    " VALUES (:uid, :node, :version)"
                    " RETURNING node_id, created_at, since_version"
                ),
                {"uid": user_id, "node": node_id, "version": version},
            )
        )
        .mappings()
        .one()
    )
    return _follow(row)


async def follow(db: AsyncSession, user: CurrentUser, node_id: str) -> Follow:
    """Follow a disease of the atlas (idempotent). 404 unless it is an atlas disease, 409 at the
    limit of 50."""
    if atlas_disease(node_id) is None:
        raise ApiError(404, ErrorCode.not_found, "Only diseases in the atlas can be followed.")
    await _lock_user(db, user.id)
    existing = (
        (
            await db.execute(
                text(
                    "SELECT node_id, created_at, since_version FROM follows"
                    " WHERE user_id = :uid AND node_id = :node"
                ),
                {"uid": user.id, "node": node_id},
            )
        )
        .mappings()
        .first()
    )
    if existing is not None:
        return _follow(existing)
    if len(await _followed_ids(db, user.id)) >= MAX_FOLLOWS:
        raise ApiError(409, ErrorCode.conflict, f"You can follow at most {MAX_FOLLOWS} diseases.")
    return await _insert(db, user.id, node_id, await _data_version(db))


async def unfollow(db: AsyncSession, user: CurrentUser, node_id: str) -> None:
    """Stop following (idempotent) and delete the notifications about that disease."""
    params = {"uid": user.id, "node": node_id}
    await db.execute(text("DELETE FROM follows WHERE user_id = :uid AND node_id = :node"), params)
    await db.execute(
        text(
            "DELETE FROM notifications WHERE user_id = :uid AND subject_node_id = :node"
            " AND kind IN ('added', 'now_recruiting')"
        ),
        params,
    )


async def follow_from_profile(db: AsyncSession, user: CurrentUser) -> FollowFromProfileResult:
    """Follow the confirmed diagnoses of the health profile that are atlas diseases."""
    from backend.api.services.account import get_profile  # account imports this module

    profile = await get_profile(db, user)
    await _lock_user(db, user.id)
    followed = await _followed_ids(db, user.id)
    version = await _data_version(db)
    result = FollowFromProfileResult(
        added=[], already_following=[], not_in_atlas=[], limit_reached=False
    )
    seen: set[str] = set()
    for disease in profile.diseases:
        if disease.confirmed_at is None or disease.id in seen:
            continue
        seen.add(disease.id)
        if atlas_disease(disease.id) is None:
            result.not_in_atlas.append(disease.id)
        elif disease.id in followed:
            result.already_following.append(disease.id)
        elif len(followed) >= MAX_FOLLOWS:
            result.limit_reached = True
        else:
            result.added.append(await _insert(db, user.id, disease.id, version))
            followed.add(disease.id)
    result.added.reverse()
    return result


# ---- notifications ------------------------------------------------------------------------


async def _fill(db: AsyncSession, user_id: UUID, marker: datetime | None) -> None:
    if marker is not None:
        await db.execute(_FILL_SQL, {"uid": user_id})
    if len(_filled) >= _FILL_CACHE_MAX:
        _filled.clear()
    _filled[user_id] = marker


async def refresh(db: AsyncSession, user_id: UUID, *, force: bool) -> None:
    """Purge notifications past retention, then fill new ones (gated unless forced)."""
    from backend.api.services import suggestions  # call_match rows (connect stage 4)

    await db.execute(_PURGE_SQL, {"uid": user_id})
    marker = await db.scalar(_MARKER_SQL)
    if force or user_id not in _filled or _filled[user_id] != marker:
        await _fill(db, user_id, marker)
    await suggestions.fill_notifications(db, user_id, force=force)


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _call_notification(row: Any, titles: dict[str, str]) -> Notification:
    disease = get_graph().nodes.get(row["subject_node_id"]) if row["subject_node_id"] else None
    title = titles.get(row["ref_id"])
    try:
        call_id = UUID(row["ref_id"])
    except ValueError:
        call_id = None
    return Notification(
        id=row["id"],
        kind=NotificationKind.call_match,
        disease_id=row["subject_node_id"],
        disease_label=disease.label if disease is not None else None,
        item_id=row["ref_id"],
        call_id=call_id,
        item_type=None,
        item_label=title,
        registry_id=None,
        year=None,
        gone=title is None,
        data_version=row["data_version"],
        created_at=row["created_at"],
        read_at=row["read_at"],
    )


async def _open_call_titles(db: AsyncSession, rows: list[Any]) -> dict[str, str]:
    ids = []
    for r in rows:
        if r["kind"] == NotificationKind.call_match:
            try:
                ids.append(UUID(r["ref_id"]))
            except ValueError:
                continue
    if not ids:
        return {}
    found = await db.execute(
        text(
            "SELECT id, title FROM calls WHERE id = ANY(:ids) AND status = 'published'"
            " AND (closes_at IS NULL OR closes_at >= current_date)"
        ),
        {"ids": ids},
    )
    return {str(r[0]): r[1] for r in found}


def _notification(row: Any, titles: dict[str, str] | None = None) -> Notification:
    if row["kind"] == NotificationKind.call_match:
        return _call_notification(row, titles or {})
    nodes = get_graph().nodes
    disease = nodes.get(row["subject_node_id"]) if row["subject_node_id"] else None
    item = nodes.get(row["ref_id"])
    registry_id = year = None
    if item is not None and item.type == NodeType.trial:
        nct = item.attrs.get("nct_id")
        registry_id = nct if isinstance(nct, str) and nct else None
        if registry_id is None and _NCT.match(item.id):
            registry_id = item.id
    if item is not None and item.type == NodeType.paper:
        year = _int(item.attrs.get("year"))
    return Notification(
        id=row["id"],
        kind=NotificationKind(row["kind"]),
        disease_id=row["subject_node_id"],
        disease_label=disease.label if disease is not None else None,
        item_id=row["ref_id"],
        item_type=item.type if item is not None else None,
        item_label=item.label if item is not None else None,
        registry_id=registry_id,
        year=year,
        gone=item is None or disease is None,
        data_version=row["data_version"],
        created_at=row["created_at"],
        read_at=row["read_at"],
    )


async def _unread(db: AsyncSession, user_id: UUID) -> int:
    return int(await db.scalar(_UNREAD_SQL, {"uid": user_id}) or 0)


async def list_notifications(db: AsyncSession, user: CurrentUser, limit: int) -> NotificationList:
    await refresh(db, user.id, force=True)
    rows = list(
        (
            await db.execute(
                text(
                    "SELECT id, kind, ref_id, subject_node_id, data_version, created_at, read_at"
                    " FROM notifications WHERE user_id = :uid"
                    " AND kind IN ('added', 'now_recruiting', 'call_match')"
                    " ORDER BY created_at DESC, data_version DESC NULLS LAST, kind DESC, id"
                    " LIMIT :limit"
                ),
                {"uid": user.id, "limit": limit},
            )
        ).mappings()
    )
    titles = await _open_call_titles(db, rows)
    return NotificationList(
        items=[_notification(r, titles) for r in rows], unread_count=await _unread(db, user.id)
    )


async def unread_count(db: AsyncSession, user: CurrentUser) -> UnreadCount:
    await refresh(db, user.id, force=False)
    return UnreadCount(count=await _unread(db, user.id))


async def mark_read(db: AsyncSession, user: CurrentUser, body: MarkRead) -> UnreadCount:
    if body.all:
        await db.execute(
            text(
                "UPDATE notifications SET read_at = now() WHERE user_id = :uid AND read_at IS NULL"
            ),
            {"uid": user.id},
        )
    else:
        await db.execute(
            text(
                "UPDATE notifications SET read_at = now()"
                " WHERE user_id = :uid AND id = ANY(:ids) AND read_at IS NULL"
            ),
            {"uid": user.id, "ids": list(body.ids)},
        )
    return UnreadCount(count=await _unread(db, user.id))


# ---- consent and data rights --------------------------------------------------------------


async def delete_health_data(db: AsyncSession, user_id: UUID) -> None:
    """Withdrawal of health_data: follows and the notifications made from them, and the
    call_match notifications (made from the profile, which is deleted too)."""
    params = {"uid": user_id}
    await db.execute(
        text(
            "DELETE FROM notifications WHERE user_id = :uid"
            " AND kind IN ('added', 'now_recruiting', 'call_match')"
        ),
        params,
    )
    await db.execute(text("DELETE FROM follows WHERE user_id = :uid"), params)
    _filled.pop(user_id, None)


async def export(
    db: AsyncSession, user_id: UUID
) -> tuple[list[FollowExport], list[NotificationExport]]:
    follows = (
        await db.execute(
            text(
                "SELECT node_id, created_at, since_version FROM follows WHERE user_id = :uid"
                " ORDER BY created_at, node_id"
            ),
            {"uid": user_id},
        )
    ).mappings()
    notifications = (
        await db.execute(
            text(
                "SELECT id, kind, ref_id, subject_node_id, data_version, created_at, read_at"
                " FROM notifications WHERE user_id = :uid ORDER BY created_at, id"
            ),
            {"uid": user_id},
        )
    ).mappings()
    return (
        [FollowExport.model_validate(dict(r)) for r in follows],
        [NotificationExport.model_validate(dict(r)) for r in notifications],
    )
