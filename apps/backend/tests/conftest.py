"""Test harness: one throwaway database per test session (bootstrap -> migrate -> fixture).

Fixtures:
    test_db       session  TestDatabase with per-role URLs for the session database
    app           session  FastAPI app with lifespan, settings pointed at the session database
    client        function guest httpx.AsyncClient over ASGI (alias: guest_client)
    make_user     function async factory: await make_user(role="patient", consents=["health_data"])
                           -> TestUser(id, sub, cookies, client)
    connect_as    function async factory: await connect_as("atlas_app") -> asyncpg.Connection
                           roles: atlas (superuser), atlas_owner, atlas_app, atlas_pipeline

Set AMBER_TEST_EMBEDDINGS=0 to skip fixture embeddings (faster, no model needed).
"""

import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parents[1]
BOOTSTRAP_SQL = REPO_DIR / "deploy" / "compose" / "initdb" / "01-bootstrap.sql"
DEFAULT_BOOTSTRAP_URL = "postgresql://atlas:atlas@localhost:5432/postgres"
ROLES = ("atlas", "atlas_owner", "atlas_app", "atlas_pipeline")
BASE_URL = "http://127.0.0.1:8000"


@dataclass
class TestDatabase:
    name: str
    host_url: str  # superuser URL, any database

    def url(self, role: str = "atlas", driver: str = "postgresql") -> str:
        u = make_url(self.host_url).set(drivername=driver, database=self.name)
        if role != "atlas":
            u = u.set(username=role, password=role)
        return u.render_as_string(hide_password=False)


@dataclass
class TestUser:
    id: uuid.UUID
    sub: str
    cookies: dict[str, str]
    client: httpx.AsyncClient
    consents: list[str] = field(default_factory=list)


def _bootstrap(url: str) -> None:
    sql = BOOTSTRAP_SQL.read_text()
    for attempt in range(5):  # concurrent sessions may race on cluster-wide role DDL
        try:
            with psycopg.connect(url, autocommit=True) as conn:
                conn.execute(sql)
            return
        except (psycopg.errors.UniqueViolation, psycopg.errors.InternalError_):
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


def _base_url() -> str:
    from backend.config import get_settings

    return os.environ.get("BOOTSTRAP_DATABASE_URL") or get_settings().bootstrap_database_url


@pytest.fixture(scope="session")
def test_db() -> TestDatabase:
    host_url = _base_url() or DEFAULT_BOOTSTRAP_URL
    db = TestDatabase(name=f"atlas_test_{uuid.uuid4().hex[:12]}", host_url=host_url)
    with psycopg.connect(make_url(host_url).render_as_string(False), autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{db.name}"')
    try:
        _bootstrap(db.url())
        env = {
            "DATABASE_URL": db.url("atlas_app", "postgresql+asyncpg"),
            "MIGRATION_DATABASE_URL": db.url("atlas_owner", "postgresql+psycopg"),
            "PIPELINE_DATABASE_URL": db.url("atlas_pipeline"),
            "BOOTSTRAP_DATABASE_URL": host_url,
            "SESSION_SECRET": "test-session-secret-not-for-production-use",
            "FRONTEND_URL": "http://127.0.0.1:3100",
            "COOKIE_SECURE": "false",
            "DEMO_MODE": "false",
        }
        os.environ.update(env)
        from backend.config import get_settings

        get_settings.cache_clear()

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        cfg.set_main_option("sqlalchemy.url", env["MIGRATION_DATABASE_URL"])
        cfg.attributes["configure_logger"] = False
        command.upgrade(cfg, "head")

        from backend.fixtures.load import load_fixture

        load_fixture(
            env["PIPELINE_DATABASE_URL"],
            embeddings=os.environ.get("AMBER_TEST_EMBEDDINGS", "1") != "0",
        )
        yield db
    finally:
        with psycopg.connect(make_url(host_url).render_as_string(False), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{db.name}" WITH (FORCE)')


@pytest.fixture(scope="session")
async def app(test_db: TestDatabase):
    from backend.config import get_settings
    from backend.main import create_app

    application = create_app(get_settings())
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as c:
        yield c


@pytest.fixture
async def guest_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    return client


@pytest.fixture
async def connect_as(test_db: TestDatabase) -> AsyncIterator[Callable[..., Awaitable]]:
    conns: list[asyncpg.Connection] = []

    async def _connect(role: str = "atlas_app") -> asyncpg.Connection:
        assert role in ROLES, role
        conn = await asyncpg.connect(test_db.url(role))
        conns.append(conn)
        return conn

    yield _connect
    for conn in conns:
        await conn.close()


async def create_user(
    test_db: TestDatabase,
    *,
    role: str | None = "patient",
    consents: list[str] = (),
    sub: str | None = None,
    age_confirmed: bool = True,
) -> tuple[uuid.UUID, str]:
    """Create a user like the auth callback does (atlas_app + SECURITY DEFINER function)."""
    sub = sub or f"test-sub-{uuid.uuid4().hex}"
    conn = await asyncpg.connect(test_db.url("atlas_app"))
    try:
        uid = await conn.fetchval(
            "SELECT auth_find_or_create_user($1, $2, $3)", sub, f"{sub}@example.test", "Test"
        )
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.user_id', $1, true)", str(uid))
            await conn.execute(
                "UPDATE profiles SET role = $2, age_confirmed_at = CASE WHEN $3 THEN now() END"
                " WHERE user_id = $1",
                uid,
                role,
                age_confirmed,
            )
            for consent in consents:
                await conn.execute(
                    "INSERT INTO consents (user_id, consent_type, version) VALUES ($1, $2, 'v1')",
                    uid,
                    consent,
                )
    finally:
        await conn.close()
    return uid, sub


@pytest.fixture
async def make_user(app, test_db: TestDatabase) -> AsyncIterator[Callable[..., Awaitable]]:
    from backend.api.security import COOKIE_NAME, create_session_token

    clients: list[httpx.AsyncClient] = []

    async def _make(
        role: str | None = "patient",
        consents: list[str] = (),
        sub: str | None = None,
        age_confirmed: bool = True,
    ) -> TestUser:
        uid, sub = await create_user(
            test_db, role=role, consents=list(consents), sub=sub, age_confirmed=age_confirmed
        )
        cookies = {COOKIE_NAME: create_session_token(uid)}
        c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE_URL, cookies=cookies
        )
        clients.append(c)
        return TestUser(id=uid, sub=sub, cookies=cookies, client=c, consents=list(consents))

    yield _make
    for c in clients:
        await c.aclose()
