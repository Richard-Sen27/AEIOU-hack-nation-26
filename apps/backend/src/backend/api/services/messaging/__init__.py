"""Messaging between patients and professionals (connect consent).

Everything runs in the signed-in user's own transaction under row-level security: a user sees
only threads they take part in and their messages; cross-user steps go through the SECURITY
DEFINER functions of migration a4c7e9b2d6f8 (`open_card_thread`, `messaging_blocked`).

Safety rules: a patient opens a thread with a visible, verified professional who accepts messages,
addressed by card (never by user id), as a request of one message that the professional accepts or
declines; professionals never start a thread with a patient; at most 5 new threads per day.
No model reads messages and nothing rewrites them; bodies are encrypted at rest and never logged
or put in error messages; no attachments; plain text only.
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.api.services import connect
from backend.api.services.messaging import crypto
from backend.schemas.account import CurrentUser
from backend.schemas.enums import ErrorCode, Role
from backend.schemas.messaging import (
    DAILY_THREAD_LIMIT,
    GUARDIAN_TEXT_VERSION,
    INACTIVE_MONTHS,
    MAX_THREADS_PAGE,
    REPORT_AUTHORIZATION_VERSION,
    AgeGroup,
    Block,
    BlockList,
    ConnectExport,
    Counterpart,
    Message,
    MessageExport,
    MessageUnreadCount,
    OpenThreadRequest,
    Report,
    ReportReason,
    ReportRequest,
    SendMessageRequest,
    ThreadDetail,
    ThreadExport,
    ThreadList,
    ThreadOrigin,
    ThreadRole,
    ThreadStatus,
    ThreadSummary,
)

log = logging.getLogger(__name__)

PROFESSIONAL_ROLES = frozenset({Role.doctor, Role.researcher})

_THREAD_COLUMNS = (
    "t.id, t.opener_id, t.recipient_id, t.origin, t.recipient_card_id, t.opener_name,"
    " t.recipient_name, t.status, t.created_at, t.accepted_at, t.closed_at, t.last_message_at"
)
_VISIBLE = "(r.hidden_at IS NULL OR t.last_message_at > r.hidden_at)"
_UNREAD = (
    "(SELECT count(*) FROM messages m WHERE m.thread_id = t.id AND m.sender_id <> :uid"
    " AND m.created_at > COALESCE(r.last_read_at, '-infinity'::timestamptz))"
)
_THREAD_SQL = f"""
    SELECT {_THREAD_COLUMNS}, r.last_read_at, r.hidden_at, r.guardian_agreed_at,
           r.guardian_text_version, {_UNREAD} AS unread,
           EXISTS (SELECT 1 FROM blocks b WHERE b.user_id = :uid AND b.blocked_user_id =
                   CASE WHEN t.opener_id = :uid THEN t.recipient_id ELSE t.opener_id END)
             AS blocked_by_me
      FROM threads t
      LEFT JOIN thread_reads r ON r.thread_id = t.id AND r.user_id = :uid
"""
_PURGE_SQL = text(
    "DELETE FROM threads WHERE (opener_id = :uid OR recipient_id = :uid)"
    f" AND COALESCE(last_message_at, created_at) < now() - interval '{INACTIVE_MONTHS} months'"
)


def _require_crypto() -> None:
    if not crypto.configured():
        raise ApiError(501, ErrorCode.not_implemented, "Messaging is not set up on this server.")


def _not_found() -> ApiError:
    return ApiError(404, ErrorCode.not_found, "Conversation not found.")


def _body(ciphertext: Any) -> str | None:
    try:
        return crypto.decrypt(ciphertext)
    except crypto.MessageCryptoError:
        log.warning("message body could not be decrypted")
        return None


def _summary(row: Any, user_id: UUID, group: AgeGroup | None) -> ThreadSummary:
    mine_opener = row["opener_id"] == user_id
    other_id = row["recipient_id"] if mine_opener else row["opener_id"]
    status = ThreadStatus(row["status"])
    return ThreadSummary(
        id=row["id"],
        origin=ThreadOrigin(row["origin"]),
        status=status,
        my_role=ThreadRole.opener if mine_opener else ThreadRole.recipient,
        counterpart=Counterpart(
            name=row["recipient_name"] if mine_opener else row["opener_name"],
            is_professional=mine_opener,
            card_id=row["recipient_card_id"] if mine_opener else None,
            deleted=other_id is None,
        ),
        created_at=row["created_at"],
        last_message_at=row["last_message_at"],
        unread_count=int(row["unread"] or 0),
        can_send=status == ThreadStatus.open and other_id is not None,
        can_respond=status == ThreadStatus.requested and not mine_opener,
        blocked_by_me=bool(row["blocked_by_me"]),
        guardian_agreement_needed=group == AgeGroup.minor and row["guardian_agreed_at"] is None,
    )


async def _thread_row(db: AsyncSession, user_id: UUID, thread_id: UUID) -> Any:
    row = (
        (
            await db.execute(
                text(_THREAD_SQL + " WHERE t.id = :tid"), {"uid": user_id, "tid": thread_id}
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise _not_found()
    return row


async def _messages(db: AsyncSession, user_id: UUID, thread_id: UUID) -> list[Message]:
    rows = (
        await db.execute(
            text(
                "SELECT id, sender_id, body_enc, created_at FROM messages WHERE thread_id = :tid"
                " ORDER BY created_at, id"
            ),
            {"tid": thread_id},
        )
    ).mappings()
    return [
        Message(
            id=r["id"],
            mine=r["sender_id"] == user_id,
            body=_body(r["body_enc"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]


async def _mark_read(db: AsyncSession, user_id: UUID, thread_id: UUID) -> None:
    await db.execute(
        text(
            "INSERT INTO thread_reads (thread_id, user_id, last_read_at)"
            " VALUES (:tid, :uid, clock_timestamp())"
            " ON CONFLICT (thread_id, user_id) DO UPDATE SET last_read_at = clock_timestamp()"
        ),
        {"tid": thread_id, "uid": user_id},
    )


async def purge_inactive(db: AsyncSession, user_id: UUID) -> None:
    """Delete my threads inactive for 12 months (at read time, like notifications)."""
    await db.execute(_PURGE_SQL, {"uid": user_id})


# ---- reading --------------------------------------------------------------------------------


async def list_threads(db: AsyncSession, user: CurrentUser) -> ThreadList:
    await purge_inactive(db, user.id)
    group = await connect.age_group(db, user.id)
    rows = (
        await db.execute(
            text(
                _THREAD_SQL + f" WHERE {_VISIBLE}"
                " ORDER BY COALESCE(t.last_message_at, t.created_at) DESC, t.id LIMIT :limit"
            ),
            {"uid": user.id, "limit": MAX_THREADS_PAGE},
        )
    ).mappings()
    items = [_summary(r, user.id, group) for r in rows]
    return ThreadList(
        items=items,
        unread_total=sum(i.unread_count for i in items),
        requests_waiting=sum(1 for i in items if i.can_respond),
    )


async def get_thread(
    db: AsyncSession, user: CurrentUser, thread_id: UUID, *, mark_read: bool = True
) -> ThreadDetail:
    row = await _thread_row(db, user.id, thread_id)
    messages = await _messages(db, user.id, thread_id)
    if mark_read:
        await _mark_read(db, user.id, thread_id)
        row = await _thread_row(db, user.id, thread_id)
    group = await connect.age_group(db, user.id)
    return ThreadDetail(thread=_summary(row, user.id, group), messages=messages)


async def unread_count(db: AsyncSession, user: CurrentUser) -> MessageUnreadCount:
    await purge_inactive(db, user.id)
    row = (
        (
            await db.execute(
                text(
                    f"""
                    SELECT COALESCE(sum({_UNREAD}), 0) AS unread,
                           count(*) FILTER (WHERE t.status = 'requested'
                                            AND t.recipient_id = :uid) AS requests
                      FROM threads t
                      LEFT JOIN thread_reads r ON r.thread_id = t.id AND r.user_id = :uid
                     WHERE {_VISIBLE}
                    """
                ),
                {"uid": user.id},
            )
        )
        .mappings()
        .one()
    )
    return MessageUnreadCount(count=int(row["unread"]), requests_waiting=int(row["requests"]))


# ---- opening threads --------------------------------------------------------------------------


async def _guardian_version(
    db: AsyncSession, user_id: UUID, thread_id: UUID | None, agreed: bool
) -> str | None:
    """The guardian text version to record now, or None when not needed (or already recorded).

    403 age_group_required without an age group; 403 guardian_agreement_required for a 16- or
    17-year-old's first message in a thread without the ticked checkbox."""
    group = await connect.require_age_group(db, user_id)
    if group != AgeGroup.minor:
        return None
    if thread_id is not None:
        done = await db.scalar(
            text(
                "SELECT guardian_agreed_at IS NOT NULL FROM thread_reads"
                " WHERE thread_id = :tid AND user_id = :uid"
            ),
            {"tid": thread_id, "uid": user_id},
        )
        if done:
            return None
    if not agreed:
        raise ApiError(403, ErrorCode.guardian_agreement_required)
    return GUARDIAN_TEXT_VERSION


_OPEN_ERRORS = {
    "amber:not_patient": ApiError(
        403, ErrorCode.forbidden, "Only patients and caregivers can start a conversation."
    ),
    "amber:not_available": ApiError(
        404, ErrorCode.not_found, "This person does not accept messages."
    ),
    "amber:exists": ApiError(
        409, ErrorCode.conflict, "You already have a conversation with this person."
    ),
    "amber:limit": ApiError(
        429,
        ErrorCode.rate_limited,
        f"You can start at most {DAILY_THREAD_LIMIT} new conversations a day.",
    ),
}


def _definer_error(exc: DBAPIError) -> ApiError | None:
    message = str(getattr(exc, "orig", "") or "")
    for marker, error in _OPEN_ERRORS.items():
        if marker in message:
            return error
    return None


async def open_card_thread(
    db: AsyncSession, user: CurrentUser, body: OpenThreadRequest
) -> ThreadDetail:
    """A patient's request to a professional's card: one message, accepted or declined later."""
    _require_crypto()
    if user.role != Role.patient:
        raise _OPEN_ERRORS["amber:not_patient"]
    version = await _guardian_version(db, user.id, None, body.guardian_agreed)
    ciphertext = crypto.encrypt(body.body)
    try:
        async with db.begin_nested():
            thread_id = await db.scalar(
                text(
                    "SELECT thread_id FROM open_card_thread(:card, :name, :body, :version, :limit)"
                ),
                {
                    "card": body.card_id,
                    "name": body.display_name,
                    "body": ciphertext,
                    "version": version,
                    "limit": DAILY_THREAD_LIMIT,
                },
            )
    except DBAPIError as exc:
        error = _definer_error(exc)
        if error is None:
            raise
        raise error from None
    return await get_thread(db, user, thread_id, mark_read=False)


async def open_signup_thread(
    db: AsyncSession,
    *,
    patient_id: UUID,
    publisher_id: UUID,
    call_id: UUID,
    signup_id: UUID,
    patient_name: str,
    publisher_name: str,
) -> UUID:
    """Stage 4 hook: open the thread that belongs to a sign-up. Returns the thread id.

    Call inside the patient's own transaction (app.user_id = patient_id) right after the sign-up
    row exists, with the call's publisher as recipient. The thread is open at once (the
    patient's sign-up is the first act, so no request step) and has no message yet. Counts
    towards the patient's 5 new threads per day (429 when reached). Names are the snapshots
    each side sees: the display name from the sign-up and the publisher's card name.
    Stage 4 should add foreign keys from threads.call_id / signup_id and tighten the insert
    policy `threads_signup_insert` to `EXISTS (call_signups ... patient_id = opener_id)`.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended('amber-threads:' || :uid, 0))"),
        {"uid": str(patient_id)},
    )
    today = await db.scalar(
        text(
            "SELECT count(*) FROM threads WHERE opener_id = :uid"
            " AND created_at > now() - interval '1 day'"
        ),
        {"uid": patient_id},
    )
    if int(today or 0) >= DAILY_THREAD_LIMIT:
        raise _OPEN_ERRORS["amber:limit"]
    return await db.scalar(
        text(
            "INSERT INTO threads (opener_id, recipient_id, origin, call_id, signup_id,"
            " opener_name, recipient_name, status)"
            " VALUES (:uid, :rid, 'signup', :call, :signup, :oname, :rname, 'open') RETURNING id"
        ),
        {
            "uid": patient_id,
            "rid": publisher_id,
            "call": call_id,
            "signup": signup_id,
            "oname": patient_name,
            "rname": publisher_name,
        },
    )


# ---- acting on a thread -------------------------------------------------------------------------


async def _set_status(db: AsyncSession, thread_id: UUID, status: ThreadStatus) -> None:
    await db.execute(
        text("UPDATE threads SET status = :s WHERE id = :tid"),
        {"s": status.value, "tid": thread_id},
    )


async def respond(
    db: AsyncSession, user: CurrentUser, thread_id: UUID, *, accept: bool
) -> ThreadDetail:
    """Accept or decline a request (only its recipient)."""
    row = await _thread_row(db, user.id, thread_id)
    if row["recipient_id"] != user.id or row["status"] != ThreadStatus.requested:
        raise ApiError(409, ErrorCode.conflict, "There is no request waiting for you here.")
    await _set_status(db, thread_id, ThreadStatus.open if accept else ThreadStatus.declined)
    return await get_thread(db, user, thread_id)


async def send_message(
    db: AsyncSession, user: CurrentUser, thread_id: UUID, body: SendMessageRequest
) -> Message:
    _require_crypto()
    row = await _thread_row(db, user.id, thread_id)
    if (
        row["status"] != ThreadStatus.open
        or row["opener_id"] is None
        or (row["recipient_id"] is None)
    ):
        raise ApiError(409, ErrorCode.conflict, "This conversation is not open for messages.")
    version = await _guardian_version(db, user.id, thread_id, body.guardian_agreed)
    ciphertext = crypto.encrypt(body.body)
    try:
        async with db.begin_nested():
            created = (
                (
                    await db.execute(
                        text(
                            "INSERT INTO messages (thread_id, sender_id, body_enc)"
                            " VALUES (:tid, :uid, :body) RETURNING id, created_at"
                        ),
                        {"tid": thread_id, "uid": user.id, "body": ciphertext},
                    )
                )
                .mappings()
                .one()
            )
    except DBAPIError:  # the policy refused (blocked or closed meanwhile)
        raise ApiError(
            409, ErrorCode.conflict, "This conversation is not open for messages."
        ) from None
    await db.execute(
        text("UPDATE threads SET last_message_at = :at WHERE id = :tid"),
        {"at": created["created_at"], "tid": thread_id},
    )
    await db.execute(
        text(
            "INSERT INTO thread_reads (thread_id, user_id, last_read_at, guardian_agreed_at,"
            " guardian_text_version)"
            " VALUES (:tid, :uid, clock_timestamp(), CASE WHEN CAST(:v AS text) IS NOT NULL"
            " THEN now() END, CAST(:v AS text))"
            " ON CONFLICT (thread_id, user_id) DO UPDATE SET last_read_at = clock_timestamp(),"
            " hidden_at = NULL,"
            " guardian_agreed_at = COALESCE(thread_reads.guardian_agreed_at,"
            " EXCLUDED.guardian_agreed_at),"
            " guardian_text_version = COALESCE(thread_reads.guardian_text_version,"
            " EXCLUDED.guardian_text_version)"
        ),
        {"tid": thread_id, "uid": user.id, "v": version},
    )
    return Message(id=created["id"], mine=True, body=body.body, created_at=created["created_at"])


async def delete_message(
    db: AsyncSession, user: CurrentUser, thread_id: UUID, message_id: UUID
) -> None:
    """Delete my own message for both sides."""
    deleted = await db.scalar(
        text(
            "DELETE FROM messages WHERE id = :mid AND thread_id = :tid AND sender_id = :uid"
            " RETURNING id"
        ),
        {"mid": message_id, "tid": thread_id, "uid": user.id},
    )
    if deleted is None:
        raise ApiError(404, ErrorCode.not_found, "Message not found.")


async def hide_thread(db: AsyncSession, user: CurrentUser, thread_id: UUID) -> None:
    """Hide a thread from my list until a new message arrives (the other side is unaffected)."""
    await _thread_row(db, user.id, thread_id)
    await db.execute(
        text(
            "INSERT INTO thread_reads (thread_id, user_id, hidden_at) VALUES (:tid, :uid, now())"
            " ON CONFLICT (thread_id, user_id) DO UPDATE SET hidden_at = now()"
        ),
        {"tid": thread_id, "uid": user.id},
    )


# ---- blocking and reporting ---------------------------------------------------------------------

_PAIR = (
    "((opener_id = :uid AND recipient_id = :other) OR (opener_id = :other AND recipient_id = :uid))"
)


async def block(db: AsyncSession, user: CurrentUser, thread_id: UUID) -> None:
    """Block the other person of a thread: no messages or new threads either way."""
    row = await _thread_row(db, user.id, thread_id)
    mine_opener = row["opener_id"] == user.id
    other = row["recipient_id"] if mine_opener else row["opener_id"]
    if other is None:
        raise ApiError(409, ErrorCode.conflict, "This account no longer exists.")
    await db.execute(
        text(
            "INSERT INTO blocks (user_id, blocked_user_id, blocked_name)"
            " VALUES (:uid, :other, :name) ON CONFLICT (user_id, blocked_user_id) DO NOTHING"
        ),
        {
            "uid": user.id,
            "other": other,
            "name": row["recipient_name"] if mine_opener else row["opener_name"],
        },
    )
    await db.execute(
        text(
            f"UPDATE threads SET status = 'blocked' WHERE {_PAIR}"
            " AND status IN ('requested', 'open')"
        ),
        {"uid": user.id, "other": other},
    )


async def list_blocks(db: AsyncSession, user: CurrentUser) -> BlockList:
    rows = (
        await db.execute(
            text(
                "SELECT id, blocked_name AS name, created_at FROM blocks WHERE user_id = :uid"
                " ORDER BY created_at DESC, id"
            ),
            {"uid": user.id},
        )
    ).mappings()
    return BlockList(items=[Block.model_validate(dict(r)) for r in rows])


async def unblock(db: AsyncSession, user: CurrentUser, block_id: UUID) -> None:
    """Lift my block; threads it blocked reopen unless the other side blocks me too."""
    other = await db.scalar(
        text("DELETE FROM blocks WHERE id = :bid AND user_id = :uid RETURNING blocked_user_id"),
        {"bid": block_id, "uid": user.id},
    )
    if other is None:
        raise ApiError(404, ErrorCode.not_found, "Block not found.")
    await db.execute(
        text(
            "UPDATE threads SET status = CASE WHEN accepted_at IS NOT NULL OR origin = 'signup'"
            " THEN 'open' ELSE 'requested' END"
            f" WHERE {_PAIR} AND status = 'blocked'"
            " AND NOT messaging_blocked(opener_id, recipient_id)"
        ),
        {"uid": user.id, "other": other},
    )


async def report(
    db: AsyncSession, user: CurrentUser, thread_id: UUID, body: ReportRequest
) -> Report:
    """Report a thread (optionally one message). Authorizes the operator to read it (logged)."""
    await _thread_row(db, user.id, thread_id)
    if body.message_id is not None:
        found = await db.scalar(
            text("SELECT 1 FROM messages WHERE id = :mid AND thread_id = :tid"),
            {"mid": body.message_id, "tid": thread_id},
        )
        if not found:
            raise ApiError(404, ErrorCode.not_found, "Message not found.")
    row = (
        (
            await db.execute(
                text(
                    "INSERT INTO reports (user_id, thread_id, message_id, reason,"
                    " authorization_version) VALUES (:uid, :tid, :mid, :reason, :v)"
                    " RETURNING id, thread_id, message_id, reason, authorization_version,"
                    " created_at, reviewed_at"
                ),
                {
                    "uid": user.id,
                    "tid": thread_id,
                    "mid": body.message_id,
                    "reason": body.reason.value,
                    "v": REPORT_AUTHORIZATION_VERSION,
                },
            )
        )
        .mappings()
        .one()
    )
    return _report(row)


def _report(row: Any) -> Report:
    return Report(
        id=row["id"],
        thread_id=row["thread_id"],
        message_id=row["message_id"],
        reason=ReportReason(row["reason"]),
        authorization_version=row["authorization_version"],
        created_at=row["created_at"],
        reviewed_at=row["reviewed_at"],
    )


# ---- consent, role and data rights --------------------------------------------------------------


async def on_connect_withdrawn(db: AsyncSession, user_id: UUID) -> None:
    """Withdrawal of `connect`: delete the user's messages, close their threads. Blocks and
    reports stay (safety records, deleted with the account)."""
    params = {"uid": user_id}
    await db.execute(text("DELETE FROM messages WHERE sender_id = :uid"), params)
    await db.execute(
        text(
            "UPDATE threads SET status = 'closed' WHERE (opener_id = :uid OR recipient_id = :uid)"
            " AND status IN ('requested', 'open', 'blocked')"
        ),
        params,
    )


async def on_role_change(db: AsyncSession, user_id: UUID, new_role: Role) -> None:
    """Leaving the doctor and researcher roles closes the threads addressed to the user as a
    professional; the messages stay readable for both sides."""
    if new_role in PROFESSIONAL_ROLES:
        return
    await db.execute(
        text(
            "UPDATE threads SET status = 'closed' WHERE recipient_id = :uid"
            " AND status IN ('requested', 'open', 'blocked')"
        ),
        {"uid": user_id},
    )


async def on_account_delete(db: AsyncSession, user_id: UUID) -> None:
    """Before the user row is deleted: delete threads whose other side is already gone. The
    cascade then removes the user's messages, read markers, blocks and reports; in the remaining
    threads the user's id and name become NULL and the thread closes (trigger threads_guard),
    so the other side sees a placeholder."""
    await db.execute(
        text(
            "DELETE FROM threads WHERE (opener_id = :uid OR recipient_id = :uid)"
            " AND (opener_id IS NULL OR recipient_id IS NULL)"
        ),
        {"uid": user_id},
    )


async def export(db: AsyncSession, user_id: UUID) -> ConnectExport:
    """The user's threads with their own messages, blocks and reports (no other user's data)."""
    params = {"uid": user_id}
    age = await connect.age_group(db, user_id)
    age_at = await db.scalar(
        text("SELECT connect_age_group_at FROM profiles WHERE user_id = :uid"), params
    )
    threads = (
        await db.execute(
            text(
                f"SELECT {_THREAD_COLUMNS}, r.last_read_at, r.hidden_at, r.guardian_agreed_at,"
                " r.guardian_text_version FROM threads t"
                " LEFT JOIN thread_reads r ON r.thread_id = t.id AND r.user_id = :uid"
                " ORDER BY t.created_at, t.id"
            ),
            params,
        )
    ).mappings()
    own: dict[UUID, list[MessageExport]] = {}
    for m in (
        await db.execute(
            text(
                "SELECT id, thread_id, body_enc, created_at FROM messages WHERE sender_id = :uid"
                " ORDER BY created_at, id"
            ),
            params,
        )
    ).mappings():
        own.setdefault(m["thread_id"], []).append(
            MessageExport(id=m["id"], body=_body(m["body_enc"]), created_at=m["created_at"])
        )
    items = []
    for t in threads:
        opener = t["opener_id"] == user_id
        items.append(
            ThreadExport(
                id=t["id"],
                origin=ThreadOrigin(t["origin"]),
                status=ThreadStatus(t["status"]),
                my_role=ThreadRole.opener if opener else ThreadRole.recipient,
                counterpart_name=t["recipient_name"] if opener else t["opener_name"],
                my_display_name=t["opener_name"] if opener else t["recipient_name"],
                created_at=t["created_at"],
                accepted_at=t["accepted_at"],
                closed_at=t["closed_at"],
                last_message_at=t["last_message_at"],
                last_read_at=t["last_read_at"],
                hidden_at=t["hidden_at"],
                guardian_agreed_at=t["guardian_agreed_at"],
                guardian_text_version=t["guardian_text_version"],
                my_messages=own.get(t["id"], []),
            )
        )
    reports = (
        await db.execute(
            text(
                "SELECT id, thread_id, message_id, reason, authorization_version, created_at,"
                " reviewed_at FROM reports WHERE user_id = :uid ORDER BY created_at, id"
            ),
            params,
        )
    ).mappings()
    return ConnectExport(
        age_group=age,
        age_group_set_at=age_at,
        threads=items,
        blocks=(await _export_blocks(db, user_id)),
        reports=[_report(r) for r in reports],
    )


async def _export_blocks(db: AsyncSession, user_id: UUID) -> list[Block]:
    rows = (
        await db.execute(
            text(
                "SELECT id, blocked_name AS name, created_at FROM blocks WHERE user_id = :uid"
                " ORDER BY created_at, id"
            ),
            {"uid": user_id},
        )
    ).mappings()
    return [Block.model_validate(dict(r)) for r in rows]


__all__ = [
    "block",
    "delete_message",
    "export",
    "get_thread",
    "hide_thread",
    "list_blocks",
    "list_threads",
    "on_account_delete",
    "on_connect_withdrawn",
    "on_role_change",
    "open_card_thread",
    "open_signup_thread",
    "purge_inactive",
    "report",
    "respond",
    "send_message",
    "unblock",
    "unread_count",
]
