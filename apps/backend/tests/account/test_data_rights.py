"""GET /me/export and DELETE /me."""

import json

from account_helpers import ASSET, assert_error

from backend.api.security import COOKIE_NAME
from backend.db.models import USER_TABLES

OWNER_COLUMN = {t: ("id" if t == "users" else "user_id") for t in USER_TABLES}


async def seed_everything(connect_as, user, edge_id: str) -> None:
    app = await connect_as("atlas_app")
    async with app.transaction():
        await app.execute("SELECT set_config('app.user_id', $1, true)", str(user.id))
        await app.execute(
            "INSERT INTO openai_tokens (user_id, client_id, access_token_enc, refresh_token_enc,"
            " id_token_enc, scopes, expires_at)"
            " VALUES ($1, 'client', 'SECRET-ACCESS', 'SECRET-REFRESH', 'SECRET-ID',"
            " ARRAY['openid','email'], now() + interval '1 hour')",
            user.id,
        )
        session = await app.fetchval(
            "INSERT INTO chat_sessions (user_id, title) VALUES ($1, 'STXBP1') RETURNING id",
            user.id,
        )
        await app.execute(
            "INSERT INTO chat_messages (session_id, user_id, role, content)"
            " VALUES ($1, $2, 'user', 'my daughter has seizures')",
            session,
            user.id,
        )
        doc = await app.fetchval(
            "INSERT INTO documents (user_id) VALUES ($1) RETURNING id", user.id
        )
        await app.execute(
            "INSERT INTO findings (document_id, user_id, type, value) VALUES ($1, $2, 'gene', 'X')",
            doc,
            user.id,
        )
        await app.execute(
            "INSERT INTO jobs (user_id, kind, document_id) VALUES ($1, 'document_extraction', $2)",
            user.id,
            doc,
        )
        await app.execute(
            "INSERT INTO patient_profiles (user_id, profile) VALUES ($1, $2::jsonb)",
            user.id,
            json.dumps({"genes": [{"id": "HGNC:11444", "label": "STXBP1", "source": "chat"}]}),
        )
    assert (await user.client.post("/contributions", json=ASSET)).status_code == 201
    r = await user.client.post(f"/edges/{edge_id}/flag", json={"reason": "Wrong relation type"})
    assert r.status_code == 201, r.text


async def test_guest(client):
    assert_error(await client.get("/me/export"), 401, "sign_in_required")
    assert_error(await client.delete("/me"), 401, "sign_in_required")


async def test_export_contains_everything_and_no_secrets(make_user, connect_as, edge_ids):
    user = await make_user(consents=["health_data", "contribute"])
    await seed_everything(connect_as, user, edge_ids[0])
    r = await user.client.get("/me/export")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["account"]["id"] == str(user.id)
    assert data["account"]["email"] == f"{user.sub}@example.test"
    assert data["settings"]["role"] == "patient"
    assert data["openai_connected"] is True
    assert data["openai_connection"]["scopes"] == ["openid", "email"]
    assert data["openai_connection"]["expires_at"]
    assert {c["consent_type"] for c in data["consents"]} == {"health_data", "contribute"}
    assert data["patient_profile"]["genes"][0]["id"] == "HGNC:11444"
    assert data["chat_sessions"][0]["messages"][0]["content"] == "my daughter has seizures"
    assert len(data["documents"]) == 1
    assert len(data["findings"]) == 1
    assert len(data["jobs"]) == 1
    assert data["contributions"][0]["payload"]["name"] == ASSET["payload"]["name"]
    assert data["edge_flags"][0]["edge_id"] == edge_ids[0]
    assert "SECRET" not in r.text
    assert "client" not in json.dumps(data["openai_connection"])


async def test_export_is_own_data_only(make_user, connect_as, edge_ids):
    a = await make_user(consents=["health_data", "contribute"])
    await seed_everything(connect_as, a, edge_ids[0])
    b = await make_user()
    data = (await b.client.get("/me/export")).json()
    assert data["account"]["id"] == str(b.id)
    for key in (
        "consents",
        "chat_sessions",
        "documents",
        "findings",
        "contributions",
        "edge_flags",
        "jobs",
    ):
        assert data[key] == [], key
    assert data["patient_profile"] is None
    assert data["openai_connected"] is False


async def test_delete_leaves_nothing(make_user, connect_as, edge_ids, superuser):
    user = await make_user(consents=["health_data", "contribute"])
    other = await make_user(consents=["contribute"])
    await seed_everything(connect_as, user, edge_ids[0])
    await seed_everything(connect_as, other, edge_ids[1])
    contribution_ids = {
        r["id"]
        for r in await superuser.fetch("SELECT id FROM contributions WHERE user_id = $1", user.id)
    }
    shared = {r["id"] for r in await superuser.fetch("SELECT id FROM shared_contributions()")}
    assert contribution_ids <= shared

    flags_before = await superuser.fetchval(
        "SELECT open_flags FROM edge_flag_counts() WHERE edge_id = $1", edge_ids[0]
    )
    r = await user.client.delete("/me")
    assert r.status_code == 204
    cookie = r.headers.get("set-cookie", "")
    assert COOKIE_NAME in cookie and ("Max-Age=0" in cookie or "expires=" in cookie.lower())

    for table in USER_TABLES:
        n = await superuser.fetchval(
            f"SELECT count(*) FROM {table} WHERE {OWNER_COLUMN[table]} = $1", user.id
        )
        assert n == 0, table
    shared = {r["id"] for r in await superuser.fetch("SELECT id FROM shared_contributions()")}
    assert not contribution_ids & shared
    flags_after = await superuser.fetchval(
        "SELECT open_flags FROM edge_flag_counts() WHERE edge_id = $1", edge_ids[0]
    )
    assert (flags_after or 0) == flags_before - 1

    # The other user is untouched.
    for table in ("users", "contributions", "edge_flags", "chat_messages", "openai_tokens"):
        n = await superuser.fetchval(
            f"SELECT count(*) FROM {table} WHERE {OWNER_COLUMN[table]} = $1", other.id
        )
        assert n >= 1, table

    # The old cookie no longer works.
    assert (await user.client.get("/auth/session")).json()["user"] is None
    assert_error(await user.client.get("/me/export"), 401, "sign_in_required")


async def test_delete_without_age_confirmation(make_user, superuser):
    user = await make_user(age_confirmed=False)
    assert (await user.client.delete("/me")).status_code == 204
    assert await superuser.fetchval("SELECT count(*) FROM users WHERE id = $1", user.id) == 0
