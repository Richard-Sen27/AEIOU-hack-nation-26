"""Messaging and the connect consent: /me/threads*, /me/blocks*, /me/connect*, operator CLI."""

import io
import logging
import uuid

import asyncpg
import pytest
from account_helpers import assert_error
from cryptography.fernet import Fernet

from backend.api.services.messaging import crypto, operator
from backend.config import get_settings
from backend.db.models import MESSAGING_TABLES

SECRET = "my rare-disease question 7f3a"
KEY = Fernet.generate_key().decode()  # one key for the module: rotation re-encrypts every row


@pytest.fixture(autouse=True)
def message_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "message_encryption_key", KEY)
    return KEY


async def make_pro(make_user, superuser, *, accepts: bool = True, visible: bool = True):
    pro = await make_user(role="doctor", consents=["connect"])
    card = uuid.uuid4()
    await superuser.execute(
        "UPDATE profiles SET role_verified = true, verification_method = 'orcid',"
        " verified_name = 'Dr. Ada Example', card_id = $2, card_visible = $3,"
        " accepts_patient_messages = $4, connect_age_group = '18_plus' WHERE user_id = $1",
        pro.id,
        card,
        visible,
        accepts,
    )
    pro.card_id = card
    return pro


async def make_patient(make_user, superuser, age: str | None = "18_plus", consents=("connect",)):
    user = await make_user(consents=list(consents))
    if age:
        await superuser.execute(
            "UPDATE profiles SET connect_age_group = $2 WHERE user_id = $1", user.id, age
        )
    return user


async def open_thread(patient, pro, body: str = SECRET, **extra):
    return await patient.client.post(
        "/me/threads",
        json={"card_id": str(pro.card_id), "display_name": "Mia's mum", "body": body, **extra},
    )


async def accepted_thread(patient, pro) -> str:
    r = await open_thread(patient, pro)
    assert r.status_code == 201, r.text
    tid = r.json()["thread"]["id"]
    r = await pro.client.post(f"/me/threads/{tid}/accept")
    assert r.status_code == 200, r.text
    return tid


# ---- consent and age group ----------------------------------------------------------------


async def test_connect_consent_grant_and_age_group(make_user):
    user = await make_user()
    r = await user.client.put("/me/connect/age-group", json={"age_group": "18_plus"})
    assert_error(r, 403, "consent_required")
    r = await user.client.post(
        "/consents", json={"consent_type": "connect", "version": "connect-2026-10-04"}
    )
    assert r.status_code in (200, 201), r.text
    r = await user.client.get("/me/connect")
    assert r.json()["consent_active"] is True and r.json()["age_group"] is None
    r = await user.client.put("/me/connect/age-group", json={"age_group": "16_17"})
    assert r.json()["age_group"] == "16_17"
    r = await user.client.put("/me/connect/age-group", json={"age_group": "18_plus"})
    assert r.json()["age_group"] == "18_plus" and r.json()["age_group_set_at"]


async def test_messaging_actions_need_consent(make_user, superuser):
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser, consents=())
    assert_error(await open_thread(patient, pro), 403, "consent_required")
    tid = str(uuid.uuid4())
    for path in ("accept", "decline"):
        assert_error(
            await patient.client.post(f"/me/threads/{tid}/{path}"), 403, "consent_required"
        )
    r = await patient.client.post(f"/me/threads/{tid}/messages", json={"body": "x"})
    assert_error(r, 403, "consent_required")


async def test_age_group_required_and_guardian_for_minors(make_user, superuser):
    pro = await make_pro(make_user, superuser)
    nobody = await make_patient(make_user, superuser, age=None)
    assert_error(await open_thread(nobody, pro), 403, "age_group_required")
    minor = await make_patient(make_user, superuser, age="16_17")
    assert_error(await open_thread(minor, pro), 403, "guardian_agreement_required")
    r = await open_thread(minor, pro, guardian_agreed=True)
    assert r.status_code == 201, r.text
    assert r.json()["thread"]["guardian_agreement_needed"] is False
    row = await superuser.fetchrow(
        "SELECT guardian_agreed_at, guardian_text_version FROM thread_reads WHERE user_id = $1",
        minor.id,
    )
    assert row["guardian_agreed_at"] and row["guardian_text_version"] == "guardian-2026-10-04"


async def test_minor_professional_reply_needs_guardian_once(make_user, superuser):
    pro = await make_pro(make_user, superuser)
    await superuser.execute(
        "UPDATE profiles SET connect_age_group = '16_17' WHERE user_id = $1", pro.id
    )
    patient = await make_patient(make_user, superuser)
    tid = await accepted_thread(patient, pro)
    r = await pro.client.post(f"/me/threads/{tid}/messages", json={"body": "hi"})
    assert_error(r, 403, "guardian_agreement_required")
    r = await pro.client.post(
        f"/me/threads/{tid}/messages", json={"body": "hi", "guardian_agreed": True}
    )
    assert r.status_code == 201
    r = await pro.client.post(f"/me/threads/{tid}/messages", json={"body": "again"})
    assert r.status_code == 201


# ---- the main flow ------------------------------------------------------------------------


async def test_request_accept_exchange_and_unread(make_user, superuser):
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    r = await open_thread(patient, pro)
    assert r.status_code == 201, r.text
    detail = r.json()
    tid = detail["thread"]["id"]
    assert detail["thread"]["status"] == "requested"
    assert detail["thread"]["counterpart"] == {
        "name": "Dr. Ada Example",
        "is_professional": True,
        "card_id": str(pro.card_id),
        "deleted": False,
    }
    assert str(pro.id) not in r.text
    # Patient cannot send more before acceptance.
    r = await patient.client.post(f"/me/threads/{tid}/messages", json={"body": "more"})
    assert_error(r, 409, "conflict")
    # The professional sees the request.
    r = await pro.client.get("/me/threads/unread-count")
    assert r.json() == {"count": 1, "requests_waiting": 1}
    r = await pro.client.get("/me/threads")
    item = r.json()["items"][0]
    assert item["can_respond"] and item["counterpart"]["name"] == "Mia's mum"
    assert str(patient.id) not in r.text
    assert_error(await patient.client.post(f"/me/threads/{tid}/accept"), 409, "conflict")
    r = await pro.client.post(f"/me/threads/{tid}/accept")
    assert r.json()["thread"]["status"] == "open"
    assert r.json()["messages"][0]["body"] == SECRET
    assert (await pro.client.get("/me/threads/unread-count")).json()["count"] == 0
    r = await pro.client.post(f"/me/threads/{tid}/messages", json={"body": "Hello, see <a>"})
    assert r.status_code == 201 and r.json()["mine"]
    assert (await patient.client.get("/me/threads/unread-count")).json()["count"] == 1
    r = await patient.client.get(f"/me/threads/{tid}")
    assert [m["body"] for m in r.json()["messages"]] == [SECRET, "Hello, see <a>"]
    assert (await patient.client.get("/me/threads/unread-count")).json()["count"] == 0


async def test_decline(make_user, superuser):
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    tid = (await open_thread(patient, pro)).json()["thread"]["id"]
    r = await pro.client.post(f"/me/threads/{tid}/decline")
    assert r.json()["thread"]["status"] == "declined"
    r = await pro.client.post(f"/me/threads/{tid}/messages", json={"body": "x"})
    assert_error(r, 409, "conflict")


async def test_professional_cannot_start_thread(make_user, superuser):
    pro = await make_pro(make_user, superuser)
    other = await make_pro(make_user, superuser)
    r = await open_thread(other, pro)
    assert_error(r, 403, "forbidden")
    # Not even directly through the database function.
    app = await asyncpg.connect(get_settings().database_url.replace("+asyncpg", ""))
    try:
        async with app.transaction():
            await app.execute("SELECT set_config('app.user_id', $1, true)", str(other.id))
            with pytest.raises(asyncpg.RaiseError, match="amber:not_patient"):
                await app.fetch(
                    "SELECT * FROM open_card_thread($1, 'x', 'y'::bytea, NULL, 5)", pro.card_id
                )
    finally:
        await app.close()


async def test_card_must_accept_messages(make_user, superuser):
    patient = await make_patient(make_user, superuser)
    closed = await make_pro(make_user, superuser, accepts=False)
    hidden = await make_pro(make_user, superuser, visible=False)
    for pro in (closed, hidden):
        assert_error(await open_thread(patient, pro), 404, "not_found")


async def test_duplicate_and_daily_limit(make_user, superuser):
    patient = await make_patient(make_user, superuser)
    first = await make_pro(make_user, superuser)
    assert (await open_thread(patient, first)).status_code == 201
    assert_error(await open_thread(patient, first), 409, "conflict")
    for _ in range(4):
        assert (await open_thread(patient, await make_pro(make_user, superuser))).status_code == 201
    r = await open_thread(patient, await make_pro(make_user, superuser))
    assert_error(r, 429, "rate_limited")


async def test_body_validation_never_echoes(make_user, superuser):
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    r = await open_thread(patient, pro, body=SECRET + "x" * 2001)
    assert_error(r, 422, "validation_error")
    assert SECRET not in r.text


# ---- privacy ------------------------------------------------------------------------------


async def test_only_participants_read(make_user, superuser, connect_as):
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    outsider = await make_patient(make_user, superuser)
    tid = await accepted_thread(patient, pro)
    assert_error(await outsider.client.get(f"/me/threads/{tid}"), 404, "not_found")
    assert (await outsider.client.get("/me/threads")).json()["items"] == []
    r = await outsider.client.post(f"/me/threads/{tid}/messages", json={"body": "x"})
    assert r.status_code in (403, 404)
    app = await connect_as("atlas_app")
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(outsider.id))
        for table in MESSAGING_TABLES:
            assert await app.fetchval(f"SELECT count(*) FROM {table}") == 0, table
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO messages (thread_id, sender_id, body_enc) VALUES ($1, $2, 'x')",
                uuid.UUID(tid),
                outsider.id,
            )
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(patient.id))
        assert await app.fetchval("SELECT count(*) FROM messages") == 1
        # Only the recipient may accept: the trigger refuses other transitions.
        with pytest.raises(asyncpg.PostgresError):
            await app.execute(
                "UPDATE threads SET opener_id = recipient_id WHERE id = $1", uuid.UUID(tid)
            )
    assert await app.fetchval("SELECT count(*) FROM threads") == 0  # guest
    su = await connect_as("atlas")
    for table in MESSAGING_TABLES:
        assert await su.fetchval(
            "SELECT relforcerowsecurity FROM pg_class WHERE relname = $1", table
        )


async def test_bodies_encrypted_at_rest_and_rotation(make_user, superuser, message_key):
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    await accepted_thread(patient, pro)
    stored = await superuser.fetchval(
        "SELECT body_enc FROM messages m JOIN threads t ON t.id = m.thread_id"
        " WHERE t.opener_id = $1",
        patient.id,
    )
    assert SECRET.encode() not in bytes(stored)
    assert crypto.decrypt(stored) == SECRET
    new = Fernet.generate_key().decode()
    rotated = crypto.rotate(stored, key=f"{new},{message_key}")
    assert crypto.decrypt(rotated, key=new) == SECRET
    with pytest.raises(crypto.MessageCryptoError):
        crypto.decrypt(rotated, key=message_key)


def test_dev_key_only_on_loopback(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "message_encryption_key", "")
    assert crypto.configured()  # tests run on 127.0.0.1
    monkeypatch.setattr(settings, "api_url", "https://api.example.org")
    assert not crypto.configured()


async def test_no_body_in_logs(make_user, superuser, caplog):
    caplog.set_level(logging.DEBUG)
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    tid = await accepted_thread(patient, pro)
    await patient.client.post(f"/me/threads/{tid}/messages", json={"body": SECRET + " two"})
    await patient.client.get(f"/me/threads/{tid}")
    assert SECRET not in caplog.text


# ---- block and report ---------------------------------------------------------------------


async def test_block_and_unblock(make_user, superuser):
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    tid = await accepted_thread(patient, pro)
    assert (await pro.client.post(f"/me/threads/{tid}/block")).status_code == 204
    r = await patient.client.post(f"/me/threads/{tid}/messages", json={"body": "x"})
    assert_error(r, 409, "conflict")
    assert (await patient.client.get(f"/me/threads/{tid}")).json()["thread"]["status"] == "blocked"
    assert_error(await open_thread(patient, pro), 404, "not_found")  # a block hides the card
    blocks = (await pro.client.get("/me/blocks")).json()["items"]
    assert blocks[0]["name"] == "Mia's mum"
    assert (await pro.client.delete(f"/me/blocks/{blocks[0]['id']}")).status_code == 204
    r = await patient.client.post(f"/me/threads/{tid}/messages", json={"body": "again"})
    assert r.status_code == 201


async def test_report_and_operator_read_is_logged(make_user, superuser, monkeypatch, test_db):
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    tid = await accepted_thread(patient, pro)
    r = await patient.client.post(
        f"/me/threads/{tid}/report", json={"reason": "harassment", "authorize_review": False}
    )
    assert_error(r, 422, "validation_error")
    r = await patient.client.post(
        f"/me/threads/{tid}/report", json={"reason": "harassment", "authorize_review": True}
    )
    assert r.status_code == 201, r.text
    report_id = uuid.UUID(r.json()["id"])
    monkeypatch.setattr(
        get_settings(), "migration_database_url", test_db.url("atlas_owner", "postgresql+psycopg")
    )
    with pytest.raises(SystemExit):
        operator.read_reported_thread(report_id, operator="ops", reason="short")
    out = io.StringIO()
    operator.read_reported_thread(
        report_id, operator="ops", reason="harassment report review", out=out
    )
    assert SECRET in out.getvalue()
    log = await superuser.fetchrow("SELECT * FROM admin_access_log WHERE report_id = $1", report_id)
    assert log["operator"] == "ops" and log["thread_id"] == uuid.UUID(tid)


# ---- deletion and data rights -------------------------------------------------------------


async def test_delete_own_message(make_user, superuser):
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    tid = await accepted_thread(patient, pro)
    mid = (await pro.client.post(f"/me/threads/{tid}/messages", json={"body": "x"})).json()["id"]
    r = await patient.client.delete(f"/me/threads/{tid}/messages/{mid}")
    assert_error(r, 404, "not_found")
    assert (await pro.client.delete(f"/me/threads/{tid}/messages/{mid}")).status_code == 204
    assert len((await patient.client.get(f"/me/threads/{tid}")).json()["messages"]) == 1


async def test_connect_withdrawal(make_user, superuser):
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    tid = await accepted_thread(patient, pro)
    await pro.client.post(f"/me/threads/{tid}/messages", json={"body": "reply"})
    assert (await patient.client.delete("/consents/connect")).status_code == 204
    detail = (await pro.client.get(f"/me/threads/{tid}")).json()
    assert detail["thread"]["status"] == "closed"
    assert [m["body"] for m in detail["messages"]] == ["reply"]
    assert (await patient.client.get("/me/connect")).json()["age_group"] is None


async def test_account_deletion_leaves_placeholder(make_user, superuser):
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    tid = await accepted_thread(patient, pro)
    await pro.client.post(f"/me/threads/{tid}/messages", json={"body": "reply"})
    assert (await patient.client.delete("/me")).status_code == 204
    detail = (await pro.client.get(f"/me/threads/{tid}")).json()
    assert detail["thread"]["counterpart"] == {
        "name": None,
        "is_professional": False,
        "card_id": None,
        "deleted": True,
    }
    assert detail["thread"]["status"] == "closed" and not detail["thread"]["can_send"]
    assert [m["body"] for m in detail["messages"]] == ["reply"]
    assert (
        await superuser.fetchval("SELECT count(*) FROM messages WHERE sender_id = $1", patient.id)
        == 0
    )


async def test_inactive_threads_purged_at_read(make_user, superuser):
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    tid = await accepted_thread(patient, pro)
    await superuser.execute(
        "UPDATE threads SET last_message_at = now() - interval '13 months' WHERE id = $1",
        uuid.UUID(tid),
    )
    assert (await patient.client.get("/me/threads")).json()["items"] == []
    assert (
        await superuser.fetchval("SELECT count(*) FROM threads WHERE id = $1", uuid.UUID(tid)) == 0
    )


async def test_export(make_user, superuser):
    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    tid = await accepted_thread(patient, pro)
    await pro.client.post(f"/me/threads/{tid}/messages", json={"body": "their words"})
    data = (await patient.client.get("/me/export")).json()["connect"]
    assert data["age_group"] == "18_plus"
    [thread] = data["threads"]
    assert thread["my_role"] == "opener" and thread["counterpart_name"] == "Dr. Ada Example"
    assert [m["body"] for m in thread["my_messages"]] == [SECRET]


# ---- operator commands --------------------------------------------------------------------


@pytest.fixture
def as_operator(monkeypatch, test_db):
    monkeypatch.setattr(
        get_settings(), "migration_database_url", test_db.url("atlas_owner", "postgresql+psycopg")
    )


async def test_cli_rotate_message_key(make_user, superuser, monkeypatch, message_key, as_operator):
    from backend import cli

    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    tid = await accepted_thread(patient, pro)
    new = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "message_encryption_key", f"{new},{message_key}")
    assert cli.main(["rotate-message-key"]) == 0
    monkeypatch.setattr(get_settings(), "message_encryption_key", new)
    r = await patient.client.get(f"/me/threads/{tid}")
    assert r.json()["messages"][0]["body"] == SECRET
    stored = await superuser.fetchval(
        "SELECT body_enc FROM messages WHERE thread_id = $1", uuid.UUID(tid)
    )
    with pytest.raises(crypto.MessageCryptoError):
        crypto.decrypt(stored, key=message_key)
    monkeypatch.setattr(get_settings(), "message_encryption_key", f"{message_key},{new}")
    assert cli.main(["rotate-message-key"]) == 0  # back to the module key for later tests


async def test_cli_purge_and_report_commands(make_user, superuser, as_operator, capsys):
    from backend import cli

    pro = await make_pro(make_user, superuser)
    patient = await make_patient(make_user, superuser)
    tid = uuid.UUID(await accepted_thread(patient, pro))
    r = await patient.client.post(
        f"/me/threads/{tid}/report", json={"reason": "spam", "authorize_review": True}
    )
    report_id = r.json()["id"]
    assert cli.main(["list-reports"]) == 0
    listed = capsys.readouterr().out
    assert report_id in listed and SECRET not in listed
    reason = "spam report from the reporter"
    assert (
        cli.main(["read-reported-thread", report_id, "--operator", "ops", "--reason", reason]) == 0
    )
    assert SECRET in capsys.readouterr().out
    assert (
        await superuser.fetchval(
            "SELECT reason FROM admin_access_log WHERE report_id = $1", uuid.UUID(report_id)
        )
        == reason
    )
    await superuser.execute(
        "UPDATE threads SET last_message_at = now() - interval '13 months' WHERE id = $1", tid
    )
    assert cli.main(["purge-messages"]) == 0
    assert await superuser.fetchval("SELECT count(*) FROM threads WHERE id = $1", tid) == 0
    assert await superuser.fetchval("SELECT count(*) FROM messages WHERE thread_id = $1", tid) == 0
