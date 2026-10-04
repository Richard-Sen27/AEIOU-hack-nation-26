"""Migration f3b8d2a6c4e1 keeps existing (ChatGPT) users working, on its own throwaway database."""

import importlib.util
import uuid
from pathlib import Path

import asyncpg
import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

_spec = importlib.util.spec_from_file_location(
    "root_conftest", Path(__file__).resolve().parents[1] / "conftest.py"
)
_root = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_root)
BACKEND_DIR, DEFAULT_BOOTSTRAP_URL = _root.BACKEND_DIR, _root.DEFAULT_BOOTSTRAP_URL
TestDatabase, _base_url, _bootstrap = _root.TestDatabase, _root._base_url, _root._bootstrap


async def test_existing_users_become_openai_and_keep_signing_in():
    host_url = _base_url() or DEFAULT_BOOTSTRAP_URL
    db = TestDatabase(name=f"atlas_mig_{uuid.uuid4().hex[:12]}", host_url=host_url)
    admin = make_url(host_url).render_as_string(False)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{db.name}"')
    try:
        _bootstrap(db.url())
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        cfg.set_main_option("sqlalchemy.url", db.url("atlas_owner", "postgresql+psycopg"))
        cfg.attributes["configure_logger"] = False
        command.upgrade(cfg, "e7a1c3d5f9b2")

        app = await asyncpg.connect(db.url("atlas_app"))
        try:
            old = await app.fetchval(
                "SELECT auth_find_or_create_user('chatgpt-sub', 'a@x.test', 'A')"
            )
        finally:
            await app.close()

        command.upgrade(cfg, "f3b8d2a6c4e1")

        app = await asyncpg.connect(db.url("atlas_app"))
        su = await asyncpg.connect(db.url())
        try:
            row = await su.fetchrow(
                "SELECT auth_provider, auth_subject FROM users WHERE id = $1", old
            )
            assert dict(row) == {"auth_provider": "openai", "auth_subject": "chatgpt-sub"}
            # Both function forms sign the existing ChatGPT user in.
            assert (
                await app.fetchval(
                    "SELECT auth_find_or_create_user('chatgpt-sub', 'a@x.test', 'A')"
                )
                == old
            )
            assert (
                await app.fetchval(
                    "SELECT auth_find_or_create_user('openai', 'chatgpt-sub', 'a@x.test', 'A')"
                )
                == old
            )
            google = await app.fetchval(
                "SELECT auth_find_or_create_user('google', 'chatgpt-sub', 'a@x.test', 'A')"
            )
            assert google != old  # same subject string at another provider: another account
        finally:
            await app.close()
            await su.close()

    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{db.name}" WITH (FORCE)')
