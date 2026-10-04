import asyncio
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet

from backend.api.errors import ApiError
from backend.api.security import COOKIE_NAME
from backend.api.services import auth as auth_service
from backend.db.session import user_transaction
from backend.openai_auth import TokenCryptoError, decrypt
from backend.schemas.account import CurrentUser

FRONTEND = "http://127.0.0.1:3100"
BASE_URL = "http://127.0.0.1:8000"


@pytest.fixture
async def browser(app, mock_openai_env):
    """An API client with its own cookie jar (one browser profile)."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as c:
        yield c


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


async def _approve(authorize_url: str, user: str | None = "alice", deny=False) -> str:
    extra = "&mock_decision=deny" if deny else f"&mock_user={user}"
    async with httpx.AsyncClient() as c:
        resp = await c.get(authorize_url + extra)
    assert resp.status_code == 302, resp.text
    return resp.headers["location"]


async def _follow_callback(browser: httpx.AsyncClient, location: str) -> httpx.Response:
    parts = urlsplit(location)
    assert f"{parts.scheme}://{parts.netloc}" == BASE_URL
    return await browser.get(f"{parts.path}?{parts.query}")


async def sign_in(browser, user="alice", return_to="/atlas?x=1") -> httpx.Response:
    start = await browser.get("/auth/chatgpt/start", params={"return_to": return_to})
    assert start.status_code == 302
    location = start.headers["location"]
    while True:
        callback_url = await _approve(location, user)
        resp = await _follow_callback(browser, callback_url)
        loc = resp.headers.get("location", "")
        if resp.status_code == 302 and not loc.startswith(FRONTEND):
            location = loc  # restarted with dynamic registration
            continue
        return resp


async def _user_id(connect_as, sub: str):
    conn = await connect_as("atlas")
    return await conn.fetchval(
        "SELECT id FROM users WHERE auth_provider = 'openai' AND auth_subject = $1", sub
    )


async def _token_row(connect_as, uid):
    conn = await connect_as("atlas")
    return await conn.fetchrow("SELECT * FROM openai_tokens WHERE user_id = $1", uid)


async def test_complete_sign_in(browser, mock_openai, connect_as):
    resp = await sign_in(browser)
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{FRONTEND}/atlas?x=1"
    assert COOKIE_NAME in browser.cookies
    session = (await browser.get("/auth/session")).json()
    assert session["user"]["email"] == "alice@example.test"
    assert session["user"]["name"] == "Alice Example"

    authorize = mock_openai.state.recorded("authorize")[-1]["params"]
    assert authorize["client_id"] == "dynamic_agent_client"
    assert authorize["redirect_uri"] == "http://127.0.0.1:8000/auth/callback"
    assert authorize["ext_agent_host_id"].startswith("urn:uuid:")
    assert "chatgpt.tokens.use.direct" in authorize["scope"]

    uid = await _user_id(connect_as, "user-mock-alice-0001")
    row = await _token_row(connect_as, uid)
    assert row["client_id"].startswith("oaiapp_mock_")
    assert "chatgpt.tokens.use.direct" in row["scopes"]
    assert row["expires_at"] is not None


@pytest.mark.parametrize(
    "user,suggested",
    [
        ("alice", {"first_name": "Alice Jane", "last_name": "Example"}),  # ID token claims
        ("carol", {"first_name": "Carol", "last_name": "Example"}),  # split of the name
    ],
)
async def test_work_details_prefill(browser, mock_openai, connect_as, user, suggested):
    await sign_in(browser, user)
    r = await browser.patch("/me/settings", json={"role": "doctor", "age_confirmed_16": True})
    assert r.status_code == 200, r.text
    data = (await browser.get("/me/professional")).json()
    assert data["suggested"] == {**suggested, "source": "chatgpt"}
    assert data["first_name"] is None and data["updated_at"] is None
    conn = await connect_as("atlas")
    row = await conn.fetchrow(
        "SELECT p.first_name, p.last_name, u.name FROM profiles p JOIN users u ON u.id = p.user_id"
        " WHERE u.auth_provider = 'openai' AND u.auth_subject = $1",
        f"user-mock-{user}-000{1 if user == 'alice' else 3}",
    )
    assert row["first_name"] is None and row["last_name"] is None  # nothing stored
    assert row["name"] == f"{user.title()} Example"


async def test_second_sign_in_reuses_issued_client_id(browser, mock_openai, connect_as):
    await sign_in(browser)
    first = mock_openai.state.recorded("authorize")[-1]["params"]
    uid = await _user_id(connect_as, "user-mock-alice-0001")
    issued = (await _token_row(connect_as, uid))["client_id"]
    await sign_in(browser)
    second = mock_openai.state.recorded("authorize")[-1]["params"]
    assert first["client_id"] == "dynamic_agent_client"
    assert second["client_id"] == issued
    assert "agent_name_hint" not in second
    assert second["ext_agent_host_id"] == first["ext_agent_host_id"]


async def test_remembered_client_rejected_for_other_person(browser, mock_openai, connect_as):
    await sign_in(browser, "alice")
    resp = await sign_in(browser, "bob")
    assert resp.headers["location"].startswith(FRONTEND)
    session = (await browser.get("/auth/session")).json()
    assert session["user"]["email"] == "bob@example.test"
    params = [r["params"]["client_id"] for r in mock_openai.state.recorded("authorize")]
    assert params[-1] == "dynamic_agent_client" and params[-2].startswith("oaiapp_mock_")


async def test_denied_consent(browser):
    start = await browser.get("/auth/chatgpt/start", params={"return_to": "/chat"})
    resp = await _follow_callback(browser, await _approve(start.headers["location"], deny=True))
    assert resp.headers["location"] == f"{FRONTEND}/chat?auth_error=denied"
    assert COOKIE_NAME not in browser.cookies


async def test_tampered_state(browser):
    start = await browser.get("/auth/chatgpt/start")
    callback = await _approve(start.headers["location"])
    tampered = callback.replace("state=", "state=x")
    resp = await _follow_callback(browser, tampered)
    assert resp.headers["location"] == f"{FRONTEND}/?auth_error=failed"
    assert COOKIE_NAME not in browser.cookies


async def test_missing_transaction_cookie(browser):
    start = await browser.get("/auth/chatgpt/start")
    callback = await _approve(start.headers["location"])
    browser.cookies.clear()
    resp = await _follow_callback(browser, callback)
    assert "auth_error=failed" in resp.headers["location"]


async def test_expired_transaction(browser, monkeypatch):
    start = await browser.get("/auth/chatgpt/start")
    callback = await _approve(start.headers["location"])
    monkeypatch.setattr(auth_service, "TX_TTL_S", -60)
    resp = await _follow_callback(browser, callback)
    assert "auth_error=failed" in resp.headers["location"]
    assert COOKIE_NAME not in browser.cookies


async def test_reused_state(browser):
    start = await browser.get("/auth/chatgpt/start")
    tx_cookie = browser.cookies.get(auth_service.TX_COOKIE)
    callback = await _approve(start.headers["location"])
    first = await _follow_callback(browser, callback)
    assert "auth_error" not in first.headers["location"]
    browser.cookies.clear()
    browser.cookies.set(auth_service.TX_COOKIE, tx_cookie, domain="127.0.0.1", path="/auth")
    replay = await _follow_callback(browser, callback)
    assert "auth_error=failed" in replay.headers["location"]
    assert COOKIE_NAME not in browser.cookies


@pytest.mark.parametrize(
    "return_to",
    ["//evil.example/x", "https://evil.example", "/\\evil.example", "javascript:alert(1)", "x"],
)
async def test_open_redirect_blocked(browser, return_to):
    resp = await sign_in(browser, return_to=return_to)
    assert resp.headers["location"] == f"{FRONTEND}/"


async def test_error_redirects_carry_no_details(browser, mock_openai_env, monkeypatch):
    monkeypatch.setenv("OPENAI_AUTH_ISSUER", "http://127.0.0.1:9")
    from backend.openai_auth import get_openai_settings

    get_openai_settings.cache_clear()
    resp = await browser.get("/auth/chatgpt/start", params={"return_to": "/a"})
    assert resp.headers["location"] == f"{FRONTEND}/a?auth_error=failed"


async def test_logout(browser, mock_openai, connect_as):
    await sign_in(browser)
    uid = await _user_id(connect_as, "user-mock-alice-0001")
    assert await _token_row(connect_as, uid) is not None
    resp = await browser.post("/auth/logout")
    assert resp.status_code == 204
    assert COOKIE_NAME not in browser.cookies
    assert mock_openai.state.recorded("revoke")
    assert await _token_row(connect_as, uid) is None
    assert (await browser.get("/auth/session")).json()["user"] is None


async def test_tokens_encrypted_and_isolated(browser, mock_openai, connect_as):
    await sign_in(browser)
    uid = await _user_id(connect_as, "user-mock-alice-0001")
    row = await _token_row(connect_as, uid)
    async with user_transaction(uid) as db:
        tokens = await auth_service._load_tokens(db, uid)
    assert tokens.access_token and tokens.refresh_token
    for column in ("access_token_enc", "refresh_token_enc", "id_token_enc"):
        assert tokens.access_token not in row[column]
        assert tokens.refresh_token not in row[column]
    with pytest.raises(TokenCryptoError):
        decrypt(row["access_token_enc"], key=Fernet.generate_key().decode())

    other = await connect_as("atlas_app")
    bob = await other.fetchval(
        "SELECT auth_find_or_create_user($1, $2, $3)", "isolation-sub", "x@example.test", "X"
    )
    async with other.transaction():
        await other.execute("SELECT set_config('app.user_id', $1, true)", str(bob))
        assert await other.fetchval("SELECT count(*) FROM openai_tokens") == 0
        assert await other.fetchval("DELETE FROM openai_tokens WHERE user_id = $1", uid) is None
    guest = await connect_as("atlas_app")
    assert await guest.fetchval("SELECT count(*) FROM openai_tokens") == 0


def _current(uid) -> CurrentUser:
    return CurrentUser(id=uid)


async def test_token_refresh_on_use(browser, mock_openai, connect_as):
    await sign_in(browser)
    uid = await _user_id(connect_as, "user-mock-alice-0001")
    conn = await connect_as("atlas")
    await conn.execute(
        "UPDATE openai_tokens SET expires_at = now() + interval '2 minutes',"
        " updated_at = now() - interval '58 minutes' WHERE user_id = $1",
        uid,
    )
    before = await _token_row(connect_as, uid)
    refreshes = len(
        [r for r in mock_openai.state.recorded("token") if r["grant_type"] == "refresh_token"]
    )

    llm = await auth_service.get_user_llm(_current(uid))
    assert await llm.resolve_model("main") == "gpt-mock-main"
    text = await llm.complete_text(instructions="x", input="see e_0123456789ab")
    assert "e_0123456789ab" in text

    after = await _token_row(connect_as, uid)
    assert after["refresh_token_enc"] != before["refresh_token_enc"]
    grants = [r for r in mock_openai.state.recorded("token") if r["grant_type"] == "refresh_token"]
    assert len(grants) == refreshes + 1


async def test_concurrent_refresh_rotates_once(browser, mock_openai, connect_as):
    await sign_in(browser)
    uid = await _user_id(connect_as, "user-mock-alice-0001")
    conn = await connect_as("atlas")
    await conn.execute(
        "UPDATE openai_tokens SET expires_at = now() - interval '1 minute' WHERE user_id = $1", uid
    )
    providers = [auth_service.DbTokenProvider(uid) for _ in range(4)]
    tokens = await asyncio.gather(*(p.get_token() for p in providers))
    assert len(set(tokens)) == 1
    grants = [r for r in mock_openai.state.recorded("token") if r["grant_type"] == "refresh_token"]
    assert len(grants) == 1


async def test_failed_refresh_requires_sign_in(browser, mock_openai, connect_as):
    await sign_in(browser)
    uid = await _user_id(connect_as, "user-mock-alice-0001")
    conn = await connect_as("atlas")
    await conn.execute(
        "UPDATE openai_tokens SET expires_at = now() - interval '1 minute' WHERE user_id = $1", uid
    )
    mock_openai.configure(fail_refresh=True)
    with pytest.raises(ApiError) as exc:
        await auth_service.llm_for_user(uid)
    assert exc.value.status_code == 401 and exc.value.code == "sign_in_required"
    assert await _token_row(connect_as, uid) is None
    with pytest.raises(ApiError) as api_exc:
        await auth_service.get_user_llm(_current(uid))
    assert api_exc.value.status_code == 401


async def test_identity_only_tokens_cannot_use_llm(browser, mock_openai, connect_as):
    await sign_in(browser)
    uid = await _user_id(connect_as, "user-mock-alice-0001")
    conn = await connect_as("atlas")
    await conn.execute("UPDATE openai_tokens SET scopes = '{openid,email}' WHERE user_id = $1", uid)
    with pytest.raises(ApiError) as exc:
        await auth_service.llm_for_user(uid)
    assert exc.value.status_code == 401
