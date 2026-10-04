"""Followed diseases and in-app notifications about them.

Everything here runs in the signed-in user's own transaction under row-level security: follows
and notifications are owner-only tables, and the only other input is the public graph
(`graph_changes` and the in-memory graph store). Nothing about one user is visible to another.

Notifications are filled lazily when the user reads the list or the unread count: new
`graph_changes` rows for followed diseases, from loads after the follow started, that are not
yet a notification (unique dedupe key); and `call_published` rows for listed calls (published,
open, publisher's card visible, not the user's own) that name a followed disease and were
published after the follow started (one per call, dedupe key `call|<id>`, shared with
`call_match` so a call is never notified twice). No text is stored; labels come from the current
graph and the calls table when read. The unread count fills at most once per change marker (the
newest `graph_changes` row; the newest `published_at` and the number of published calls) per
user and process, so the once-a-minute poll stays a few cheap queries. Publishers never learn
who follows a disease or who was notified: the rows live only in the follower's own table.
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
CALL_PUBLISHED = NotificationKind.call_published.value
CALL_KINDS = (NotificationKind.call_match, NotificationKind.call_published)
# The kinds shown in the list and counted; all of them rest on the health_data consent.
_KINDS_SQL = "('added', 'now_recruiting', 'call_match', 'call_published')"
_MONDO = re.compile(r"^MONDO:\d{7}$")
_NCT = re.compile(r"^NCT\d{8}$")
_FILL_CACHE_MAX = 50_000

# user id -> the change marker the user's notifications were last filled for (per process).
_filled: dict[UUID, datetime | None] = {}
# user id -> the published-calls marker the user's call_published rows were last filled for.
_calls_filled: dict[UUID, tuple[Any, ...]] = {}

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
_CALLS_MARKER_SQL = text("SELECT max(published_at), count(*) FROM calls WHERE status = 'published'")
# Listed calls (as calls.list_published: published, not expired, the publisher's card visible
# and verified) naming a followed disease, published after that follow started, not the user's
# own, within the retention period (so a purged row is not made again). One row per call; the
# subject is the first such followed disease. The dedupe key is the one call_match uses, so a
# call that is already a call_match is not notified again.
_CALLS_FILL_SQL = text(
    f"""
    INSERT INTO notifications (user_id, kind, ref_id, subject_node_id, dedupe_key)
    SELECT DISTINCT ON (c.id) f.user_id, '{CALL_PUBLISHED}', c.id::text, f.node_id,
           'call|' || c.id::text
      FROM follows f
      JOIN calls c ON f.node_id = ANY(c.disease_ids)
      JOIN call_publisher_cards() cp ON cp.call_id = c.id
      JOIN professional_cards() pc ON pc.card_id = cp.card_id
     WHERE f.user_id = :uid
       AND c.status = 'published'
       AND (c.closes_at IS NULL OR c.closes_at >= current_date)
       AND c.published_at > f.created_at
       AND c.published_at >= now() - interval '{RETENTION_DAYS} days'
       AND c.publisher_id <> :uid
     ORDER BY c.id, f.node_id
    ON CONFLICT (user_id, dedupe_key) DO NOTHING
    """
)
_UNREAD_SQL = text(
    "SELECT count(*) FROM notifications WHERE user_id = :uid AND read_at IS NULL"
    f" AND kind IN {_KINDS_SQL}"
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
    """Stop following (idempotent) and delete the notifications about that disease. A
    call_published notification whose call also names another disease the user still follows
    (followed before the call was published) moves to that disease instead of reappearing."""
    params = {"uid": user.id, "node": node_id}
    await db.execute(text("DELETE FROM follows WHERE user_id = :uid AND node_id = :node"), params)
    await db.execute(
        text(
            "DELETE FROM notifications WHERE user_id = :uid AND subject_node_id = :node"
            " AND kind IN ('added', 'now_recruiting')"
        ),
        params,
    )
    await db.execute(
        text(
            f"""
            UPDATE notifications n SET subject_node_id = (
                SELECT min(f.node_id) FROM calls c
                  JOIN follows f ON f.user_id = n.user_id AND f.node_id = ANY(c.disease_ids)
                 WHERE c.id::text = n.ref_id AND f.created_at < c.published_at)
             WHERE n.user_id = :uid AND n.kind = '{CALL_PUBLISHED}'
               AND n.subject_node_id = :node
            """
        ),
        params,
    )
    await db.execute(
        text(
            "DELETE FROM notifications WHERE user_id = :uid AND kind = :k"
            " AND subject_node_id IS NULL"
        ),
        {"uid": user.id, "k": CALL_PUBLISHED},
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


async def _fill_calls(db: AsyncSession, user_id: UUID, marker: tuple[Any, ...]) -> None:
    if marker[0] is not None:
        await db.execute(_CALLS_FILL_SQL, {"uid": user_id})
    if len(_calls_filled) >= _FILL_CACHE_MAX:
        _calls_filled.clear()
    _calls_filled[user_id] = marker


async def refresh(db: AsyncSession, user_id: UUID, *, force: bool) -> None:
    """Purge notifications past retention, then fill new ones (gated unless forced). call_match
    fills before call_published, so a call that both matches the profile and names a followed
    disease is shown once, as the more specific call_match."""
    from backend.api.services import suggestions  # call_match rows (connect stage 4)

    await db.execute(_PURGE_SQL, {"uid": user_id})
    marker = await db.scalar(_MARKER_SQL)
    if force or user_id not in _filled or _filled[user_id] != marker:
        await _fill(db, user_id, marker)
    await suggestions.fill_notifications(db, user_id, force=force)
    calls_marker = tuple((await db.execute(_CALLS_MARKER_SQL)).one())
    if force or _calls_filled.get(user_id) != calls_marker:
        await _fill_calls(db, user_id, calls_marker)


def forget_calls_fill(user_id: UUID) -> None:
    """Let the next unread-count poll fill call_published rows again (after call_match rows
    were deleted, a followed call they covered is notified as call_published)."""
    _calls_filled.pop(user_id, None)


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _call_notification(row: Any, titles: dict[str, str]) -> Notification:
    """call_match and call_published: the call's title while it is listed, else gone."""
    disease = get_graph().nodes.get(row["subject_node_id"]) if row["subject_node_id"] else None
    title = titles.get(row["ref_id"])
    try:
        call_id = UUID(row["ref_id"])
    except ValueError:
        call_id = None
    return Notification(
        id=row["id"],
        kind=NotificationKind(row["kind"]),
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
        if r["kind"] in CALL_KINDS:
            try:
                ids.append(UUID(r["ref_id"]))
            except ValueError:
                continue
    if not ids:
        return {}
    # Listed exactly as calls.list_published: published, open, the publisher's card visible.
    found = await db.execute(
        text(
            "SELECT c.id, c.title FROM calls c"
            " JOIN call_publisher_cards() cp ON cp.call_id = c.id"
            " JOIN professional_cards() pc ON pc.card_id = cp.card_id"
            " WHERE c.id = ANY(:ids) AND c.status = 'published'"
            " AND (c.closes_at IS NULL OR c.closes_at >= current_date)"
        ),
        {"ids": ids},
    )
    return {str(r[0]): r[1] for r in found}


def _notification(row: Any, titles: dict[str, str] | None = None) -> Notification:
    if row["kind"] in CALL_KINDS:
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
                    f" AND kind IN {_KINDS_SQL}"
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
    """Withdrawal of health_data: follows and the notifications made from them (including
    call_published), and the call_match notifications (made from the profile, which is deleted
    too)."""
    params = {"uid": user_id}
    await db.execute(
        text(f"DELETE FROM notifications WHERE user_id = :uid AND kind IN {_KINDS_SQL}"),
        params,
    )
    await db.execute(text("DELETE FROM follows WHERE user_id = :uid"), params)
    _filled.pop(user_id, None)
    _calls_filled.pop(user_id, None)


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
