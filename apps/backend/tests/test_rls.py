"""Row-level security proofs for every user table."""

import json
import uuid

import asyncpg
import pytest

from backend.db.models import GRAPH_TABLES, USER_TABLES

OWNER_COLUMN = {t: ("id" if t == "users" else "user_id") for t in USER_TABLES}


async def as_user(conn: asyncpg.Connection, uid: uuid.UUID | None):
    await conn.execute("SELECT set_config('app.user_id', $1, true)", str(uid) if uid else "")


async def seed_rows(conn: asyncpg.Connection, uid: uuid.UUID) -> dict[str, uuid.UUID]:
    """One row in every user table for uid (users/profiles exist via the auth function)."""
    async with conn.transaction():
        await as_user(conn, uid)
        ids: dict[str, uuid.UUID] = {}
        await conn.execute(
            "INSERT INTO openai_tokens (user_id, client_id, access_token_enc)"
            " VALUES ($1, 'c', 'x')",
            uid,
        )
        ids["consent"] = await conn.fetchval(
            "INSERT INTO consents (user_id, consent_type, version) VALUES ($1, 'contribute', 'v1')"
            " RETURNING id",
            uid,
        )
        await conn.execute(
            "INSERT INTO patient_profiles (user_id, profile) VALUES ($1, $2::jsonb)",
            uid,
            json.dumps({"diseases": []}),
        )
        ids["session"] = await conn.fetchval(
            "INSERT INTO chat_sessions (user_id, title) VALUES ($1, 't') RETURNING id", uid
        )
        ids["message"] = await conn.fetchval(
            "INSERT INTO chat_messages (session_id, user_id, role, content)"
            " VALUES ($1, $2, 'user', 'hi') RETURNING id",
            ids["session"],
            uid,
        )
        await conn.execute(
            "INSERT INTO chat_runs (user_id, session_id, user_message_id, worker)"
            " VALUES ($1, $2, $3, 'w')",
            uid,
            ids["session"],
            ids["message"],
        )
        ids["document"] = await conn.fetchval(
            "INSERT INTO documents (user_id) VALUES ($1) RETURNING id", uid
        )
        await conn.execute(
            "INSERT INTO findings (document_id, user_id, type, value) VALUES ($1, $2, 'gene', 'x')",
            ids["document"],
            uid,
        )
        await conn.execute(
            "INSERT INTO contributions (user_id, kind, consent_id) VALUES ($1, 'asset', $2)",
            uid,
            ids["consent"],
        )
        await conn.execute(
            "INSERT INTO edge_flags (edge_id, user_id, reason) VALUES ('e_shared', $1, 'r')", uid
        )
        await conn.execute(
            "INSERT INTO jobs (user_id, kind, document_id) VALUES ($1, 'document_extraction', $2)",
            uid,
            ids["document"],
        )
        await conn.execute(
            "INSERT INTO follows (user_id, node_id) VALUES ($1, 'MONDO:0100135')", uid
        )
        await conn.execute(
            "INSERT INTO notifications (user_id, kind, ref_id, subject_node_id, dedupe_key)"
            " VALUES ($1, 'added', 'NCT99000001', 'MONDO:0100135', 'k')",
            uid,
        )
    return ids


@pytest.fixture
async def two_users(connect_as):
    app = await connect_as("atlas_app")
    a = await app.fetchval(
        "SELECT auth_find_or_create_user($1, 'a@x.test', 'A')", f"a-{uuid.uuid4()}"
    )
    b = await app.fetchval(
        "SELECT auth_find_or_create_user($1, 'b@x.test', 'B')", f"b-{uuid.uuid4()}"
    )
    rows_a = await seed_rows(app, a)
    rows_b = await seed_rows(app, b)
    return app, a, b, rows_a, rows_b


async def test_every_user_table_has_rows_for_seeded_user(two_users, connect_as):
    _, a, _, _, _ = two_users
    su = await connect_as("atlas")
    for table in USER_TABLES:
        n = await su.fetchval(f"SELECT count(*) FROM {table} WHERE {OWNER_COLUMN[table]} = $1", a)
        assert n >= 1, table


async def test_no_user_sees_nothing(two_users):
    app = two_users[0]
    for table in USER_TABLES:
        assert await app.fetchval(f"SELECT count(*) FROM {table}") == 0, table
        async with app.transaction():
            await as_user(app, None)
            assert await app.fetchval(f"SELECT count(*) FROM {table}") == 0, table


async def test_user_cannot_read_other_users_rows(two_users):
    app, a, b, _, _ = two_users
    async with app.transaction():
        await as_user(app, a)
        for table in USER_TABLES:
            col = OWNER_COLUMN[table]
            assert await app.fetchval(f"SELECT count(*) FROM {table} WHERE {col} = $1", b) == 0
            own = await app.fetchval(f"SELECT count(*) FROM {table}")
            mine = await app.fetchval(f"SELECT count(*) FROM {table} WHERE {col} = $1", a)
            assert own == mine >= 1, table


async def test_user_cannot_write_other_users_rows(two_users):
    app, a, b, _, rows_b = two_users
    async with app.transaction():
        await as_user(app, a)
        for table in USER_TABLES:
            col = OWNER_COLUMN[table]
            updated = await app.execute(f"UPDATE {table} SET {col} = {col} WHERE {col} = $1", b)
            assert updated.endswith(" 0"), table
            deleted = await app.execute(f"DELETE FROM {table} WHERE {col} = $1", b)
            assert deleted.endswith(" 0"), table

    inserts = {
        "openai_tokens": ("INSERT INTO openai_tokens (user_id) VALUES ($1)", (b,)),
        "profiles": ("INSERT INTO profiles (user_id) VALUES ($1)", (b,)),
        "consents": (
            "INSERT INTO consents (user_id, consent_type, version) VALUES ($1, 'health_data', 'v')",
            (b,),
        ),
        "patient_profiles": ("INSERT INTO patient_profiles (user_id) VALUES ($1)", (b,)),
        "chat_sessions": ("INSERT INTO chat_sessions (user_id) VALUES ($1)", (b,)),
        "chat_messages": (
            "INSERT INTO chat_messages (session_id, user_id, role, content)"
            " VALUES ($2, $1, 'user', 'x')",
            (b, rows_b["session"]),
        ),
        "chat_runs": (
            "INSERT INTO chat_runs (user_id, session_id, user_message_id, worker)"
            " VALUES ($1, $2, $3, 'w')",
            (b, rows_b["session"], rows_b["message"]),
        ),
        "documents": ("INSERT INTO documents (user_id) VALUES ($1)", (b,)),
        "findings": (
            "INSERT INTO findings (document_id, user_id, type, value) VALUES ($2, $1, 'gene', 'x')",
            (b, rows_b["document"]),
        ),
        "contributions": ("INSERT INTO contributions (user_id, kind) VALUES ($1, 'asset')", (b,)),
        "edge_flags": (
            "INSERT INTO edge_flags (edge_id, user_id, reason) VALUES ('e_other', $1, 'r')",
            (b,),
        ),
        "jobs": ("INSERT INTO jobs (user_id, kind) VALUES ($1, 'document_extraction')", (b,)),
        "follows": ("INSERT INTO follows (user_id, node_id) VALUES ($1, 'MONDO:9900007')", (b,)),
        "notifications": (
            "INSERT INTO notifications (user_id, kind, ref_id, dedupe_key)"
            " VALUES ($1, 'added', 'PMID:FX0001', 'other')",
            (b,),
        ),
        "users": (
            "INSERT INTO users (id, auth_provider, auth_subject) VALUES ($1, 'openai', 'spoof')",
            (b,),
        ),
    }
    assert set(inserts) == set(USER_TABLES)
    for sql, args in inserts.values():
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            async with app.transaction():
                await as_user(app, a)
                await app.execute(sql, *args)


async def test_app_cannot_write_graph_tables(connect_as):
    app = await connect_as("atlas_app")
    for table in GRAPH_TABLES:
        assert await app.fetchval(f"SELECT count(*) >= 0 FROM {table}")
    statements = [
        "INSERT INTO nodes (id, type, label) VALUES ('X:1', 'gene', 'x')",
        "UPDATE edges SET confidence = 1",
        "DELETE FROM evidence",
        "UPDATE nodes SET label = 'x'",
        "INSERT INTO clusters (id) VALUES ('CLUSTER:99')",
        "DELETE FROM node_synonyms",
        "INSERT INTO ingestion_runs (data_version) VALUES ('evil')",
        "TRUNCATE nodes CASCADE",
        "DELETE FROM explanations_cache",
    ]
    for sql in statements:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app.execute(sql)
    tr = app.transaction()  # the explanations cache is writable (live explanations)
    await tr.start()
    await app.execute(
        "INSERT INTO explanations_cache (path_id, role, language, data_version, text)"
        " VALUES ('p_test', 'patient', 'en', 'fixture', 'x')"
    )
    await app.execute("UPDATE explanations_cache SET text = 'y' WHERE path_id = 'p_test'")
    await tr.rollback()


async def test_pipeline_cannot_read_user_tables(connect_as):
    pipe = await connect_as("atlas_pipeline")
    for table in USER_TABLES:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await pipe.fetch(f"SELECT * FROM {table} LIMIT 1")
    for fn in ("auth_find_or_create_user('s', 'e', 'n')", "edge_flag_counts()"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await pipe.fetch(f"SELECT * FROM {fn}")


async def test_app_cannot_become_definer(connect_as):
    app = await connect_as("atlas_app")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app.execute("SET ROLE atlas_definer")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app.execute("SET ROLE atlas_owner")


async def test_delete_user_cascades(two_users, connect_as):
    app, a, b, _, _ = two_users
    async with app.transaction():
        await as_user(app, a)
        assert await app.execute("DELETE FROM users WHERE id = $1", a) == "DELETE 1"
    su = await connect_as("atlas")
    for table in USER_TABLES:
        col = OWNER_COLUMN[table]
        assert await su.fetchval(f"SELECT count(*) FROM {table} WHERE {col} = $1", a) == 0, table
        assert await su.fetchval(f"SELECT count(*) FROM {table} WHERE {col} = $1", b) >= 1, table


async def test_auth_find_or_create_user(connect_as):
    app = await connect_as("atlas_app")
    su = await connect_as("atlas")
    sub = f"sub-{uuid.uuid4()}"
    first = await app.fetchval("SELECT auth_find_or_create_user($1, 'old@x.test', 'Old')", sub)
    before = await su.fetchval("SELECT last_login_at FROM users WHERE id = $1", first)
    again = await app.fetchval("SELECT auth_find_or_create_user($1, 'new@x.test', 'New')", sub)
    assert first == again
    row = await su.fetchrow("SELECT email, last_login_at FROM users WHERE id = $1", first)
    assert row["email"] == "new@x.test" and row["last_login_at"] >= before
    profile = await su.fetchrow("SELECT role, language FROM profiles WHERE user_id = $1", first)
    assert profile["role"] is None and profile["language"] == "en"
    assert await su.fetchval("SELECT count(*) FROM users WHERE auth_subject = $1", sub) == 1


async def test_edge_flag_counts_without_identities(two_users):
    app = two_users[0]
    rows = await app.fetch("SELECT * FROM edge_flag_counts()")
    counts = {r["edge_id"]: r["open_flags"] for r in rows}
    assert counts["e_shared"] >= 2
    assert set(rows[0].keys()) == {"edge_id", "open_flags"}


async def test_shared_contributions_follow_consent(two_users):
    app, a, b, rows_a, rows_b = two_users
    shared = {r["id"] for r in await app.fetch("SELECT * FROM shared_contributions()")}
    async with app.transaction():
        await as_user(app, a)
        own = await app.fetchval("SELECT id FROM contributions")
        await app.execute("UPDATE consents SET revoked_at = now() WHERE id = $1", rows_a["consent"])
    assert own in shared
    after = await app.fetch("SELECT * FROM shared_contributions()")
    assert own not in {r["id"] for r in after}
    assert "user_id" not in after[0].keys()
