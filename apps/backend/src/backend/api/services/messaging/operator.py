"""Operator tooling for messaging (CLI only, runs as atlas_owner via MIGRATION_DATABASE_URL).

- `list_reports`: open reports without any message content.
- `read_reported_thread`: prints a reported thread only after writing an `admin_access_log` row
  with the operator's name and reason, in the same transaction. The report itself is the
  reporter's authorization. Nothing else in the codebase reads message bodies of other users.
- `purge`: the 12-month deletion of inactive threads (plus orphaned threads, reports after 12
  months and access-log rows after 24 months), and sign-ups to calls past their time (stubs
  after 30 days, sign-ups of closed calls after 90). The API also deletes a user's own inactive
  threads and sign-ups at read time; run this daily for the rows nobody opens.
- `rotate_key`: re-encrypts every body under the newest MESSAGE_ENCRYPTION_KEY.
"""

import sys
from typing import TextIO
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from backend.api.services.messaging import crypto
from backend.config import get_settings
from backend.schemas.messaging import INACTIVE_MONTHS

ACCESS_LOG_MONTHS = 24
REPORT_MONTHS = 12


def _connect() -> psycopg.Connection:
    url = get_settings().migration_database_url.replace("postgresql+psycopg://", "postgresql://")
    return psycopg.connect(url, row_factory=dict_row)


def list_reports(*, out: TextIO | None = None) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, reason, thread_id, message_id, reviewed_at FROM reports"
            " ORDER BY reviewed_at IS NOT NULL, created_at"
        ).fetchall()
    for r in rows:
        state = "reviewed" if r["reviewed_at"] else "open"
        print(
            f"{r['id']}  {r['created_at']:%Y-%m-%d %H:%M}  {r['reason']:<15} {state:<9}"
            f" thread {r['thread_id'] or '(deleted)'}",
            file=out or sys.stdout,
        )
    if not rows:
        print("no reports", file=out or sys.stdout)
    return rows


def read_reported_thread(
    report_id: UUID, *, operator: str, reason: str, out: TextIO | None = None
) -> list[dict]:
    """Log the access, then print the reported thread. Refuses without a report or a reason."""
    operator, reason = operator.strip(), " ".join(reason.split())
    if not operator or len(operator) > 100:
        raise SystemExit("--operator is required (your name, at most 100 characters)")
    if not 10 <= len(reason) <= 500:
        raise SystemExit("--reason is required (10 to 500 characters); it is logged")
    with _connect() as conn, conn.transaction():
        report = conn.execute(
            "SELECT id, thread_id, message_id, reason FROM reports WHERE id = %s FOR UPDATE",
            (report_id,),
        ).fetchone()
        if report is None:
            raise SystemExit("no such report")
        if report["thread_id"] is None:
            raise SystemExit("the reported thread no longer exists")
        conn.execute(
            "INSERT INTO admin_access_log (operator, action, report_id, thread_id, reason)"
            " VALUES (%s, 'read_reported_thread', %s, %s, %s)",
            (operator, report_id, report["thread_id"], reason),
        )
        conn.execute("UPDATE reports SET reviewed_at = now() WHERE id = %s", (report_id,))
        thread = conn.execute(
            "SELECT id, origin, status, opener_id, recipient_id, opener_name, recipient_name,"
            " created_at FROM threads WHERE id = %s",
            (report["thread_id"],),
        ).fetchone()
        messages = conn.execute(
            "SELECT id, sender_id, body_enc, created_at FROM messages WHERE thread_id = %s"
            " ORDER BY created_at, id",
            (report["thread_id"],),
        ).fetchall()
    print(
        f"ACCESS LOGGED. Report {report_id} ({report['reason']}); thread {thread['id']}"
        f" ({thread['origin']}, {thread['status']}, opened {thread['created_at']:%Y-%m-%d})",
        file=out or sys.stdout,
    )
    print(
        f"opener: {thread['opener_name'] or '(deleted account)'}"
        f" · recipient: {thread['recipient_name'] or '(deleted account)'}",
        file=out or sys.stdout,
    )
    for m in messages:
        side = "opener" if m["sender_id"] == thread["opener_id"] else "recipient"
        flag = "  <- reported" if m["id"] == report["message_id"] else ""
        try:
            body = crypto.decrypt(m["body_enc"])
        except crypto.MessageCryptoError:
            body = "(could not be decrypted)"
        print(f"--- {m['created_at']:%Y-%m-%d %H:%M} {side}{flag}\n{body}", file=out or sys.stdout)
    return messages


def signups_purge_sql() -> str:
    from backend.api.services.signups import PURGE_ALL_SQL  # signups imports messaging

    return PURGE_ALL_SQL


def purge(*, out: TextIO | None = None) -> dict[str, int]:
    with _connect() as conn, conn.transaction():
        counts = {
            "threads": conn.execute(
                "DELETE FROM threads WHERE COALESCE(last_message_at, created_at)"
                f" < now() - interval '{INACTIVE_MONTHS} months'"
                " OR (opener_id IS NULL AND recipient_id IS NULL)"
            ).rowcount,
            "reports": conn.execute(
                f"DELETE FROM reports WHERE created_at < now() - interval '{REPORT_MONTHS} months'"
            ).rowcount,
            "admin_access_log": conn.execute(
                "DELETE FROM admin_access_log"
                f" WHERE created_at < now() - interval '{ACCESS_LOG_MONTHS} months'"
            ).rowcount,
            # Sign-up stubs after 30 days, sign-ups of closed calls after 90 (connect stage 4).
            "call_signups": conn.execute(signups_purge_sql()).rowcount,
        }
    print(", ".join(f"{k} deleted: {v}" for k, v in counts.items()), file=out or sys.stdout)
    return counts


def rotate_key(*, out: TextIO | None = None) -> int:
    """Re-encrypt every message body under the first key of MESSAGE_ENCRYPTION_KEY."""
    if not crypto.configured():
        raise SystemExit("MESSAGE_ENCRYPTION_KEY is not set")
    done = 0
    with _connect() as conn, conn.transaction():
        rows = conn.execute("SELECT id, body_enc FROM messages FOR UPDATE").fetchall()
        for r in rows:
            try:
                new = crypto.rotate(r["body_enc"])
            except crypto.MessageCryptoError:
                raise SystemExit(
                    f"message {r['id']} cannot be decrypted with any listed key"
                ) from None
            conn.execute("UPDATE messages SET body_enc = %s WHERE id = %s", (new, r["id"]))
            done += 1
    print(f"message bodies re-encrypted: {done}", file=out or sys.stdout)
    return done
