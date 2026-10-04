"""Sign in with Google: enablement rule, callback checks, separate accounts, model access.

Google's endpoints are faked with an httpx MockTransport (`set_http_factory`), tests only."""

import base64
import hashlib
import itertools
import json
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from backend import google_auth
from backend.api.errors import ApiError
from backend.api.security import COOKIE_NAME, create_session_token
from backend.api.services import auth as auth_service
from backend.google_auth import GoogleSettings, google_login_available
from backend.llm import LLMClient, LLMError, ServerKeyProvider
from backend.openai_auth.settings import get_openai_settings

BASE_URL = "http://127.0.0.1:8000"
FRONTEND = "http://127.0.0.1:3100"
CLIENT_ID = "test-client.apps.googleusercontent.com"
KID = "test-kid"


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


SIGNING_KEY = _key()
OTHER_KEY = _key()


class FakeGoogle:
    def __init__(self):
        self.claims: dict = {}
        self.key = SIGNING_KEY
        self.challenge: str | None = None
        self.token_form: dict | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == google_auth.GOOGLE_DISCOVERY_URL:
            return httpx.Response(
                200,
                json={
                    "authorization_endpoint": "https://accounts.google.test/auth",
                    "token_endpoint": "https://oauth2.google.test/token",
                    "jwks_uri": "https://www.google.test/certs",
                },
            )
        if url == "https://www.google.test/certs":
            jwk = json.loads(RSAAlgorithm.to_jwk(SIGNING_KEY.public_key()))
            return httpx.Response(200, json={"keys": [{**jwk, "kid": KID, "alg": "RS256"}]})
        if url == "https://oauth2.google.test/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_form = form
            digest = hashlib.sha256(form["code_verifier"].encode()).digest()
            if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != self.challenge:
                return httpx.Response(400, json={"error": "invalid_grant"})
            token = jwt.encode(self.claims, self.key, algorithm="RS256", headers={"kid": KID})
            return httpx.Response(200, json={"access_token": "unused", "id_token": token})
        return httpx.Response(404)


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_LOGIN_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    google_auth.get_google_settings.cache_clear()
    get_openai_settings.cache_clear()
    google_auth.set_http_factory(
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    )
    yield fake
    google_auth.set_http_factory(None)
    monkeypatch.undo()
    google_auth.get_google_settings.cache_clear()
    get_openai_settings.cache_clear()


@pytest.fixture
async def browser(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as c:
        yield c


def _claims(nonce: str, **over) -> dict:
    now = int(time.time())
    sub = over.pop("sub", f"g-{uuid.uuid4().hex}")
    return {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": sub,
        "email": "same@example.test",
        "email_verified": True,
        "name": "Gina Google",
        "iat": now,
        "exp": now + 600,
        "nonce": nonce,
        **over,
    }


async def _start(browser, fake) -> dict[str, str]:
    resp = await browser.get("/auth/google/start", params={"return_to": "/atlas"})
    assert resp.status_code == 302
    q = {k: v[0] for k, v in parse_qs(urlsplit(resp.headers["location"]).query).items()}
    assert q["scope"] == "openid email profile"
    assert q["code_challenge_method"] == "S256"
    assert q["client_id"] == CLIENT_ID
    assert q["redirect_uri"] == f"{BASE_URL}/auth/google/callback"
    fake.challenge = q["code_challenge"]
    return q


async def _sign_in(browser, fake, **claims) -> httpx.Response:
    q = await _start(browser, fake)
    fake.claims = _claims(claims.pop("nonce", q["nonce"]), **claims)
    return await browser.get(
        "/auth/google/callback", params={"state": q["state"], "code": "the-code"}
    )


# ---- enablement rule ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cid", "secret", "key", "flag"), list(itertools.product([True, False], repeat=4))
)
def test_enablement_rule(cid, secret, key, flag):
    s = GoogleSettings(
        google_client_id="id" if cid else "",
        google_client_secret="s" if secret else "",
        google_login_enabled=flag,
    )
    expected = cid and secret and (key or flag)
    assert google_login_available(s, "sk-x" if key else "") is expected


async def test_disabled_by_default(browser, monkeypatch):
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_LOGIN_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(google_auth, "get_google_settings", lambda: GoogleSettings(_env_file=None))
    session = (await browser.get("/auth/session")).json()
    assert session["sign_in_methods"] == ["openai"]
    assert (await browser.get("/auth/google/start")).status_code == 404
    assert (await browser.get("/auth/google/callback?state=x&code=y")).status_code == 404


# ---- flow ---------------------------------------------------------------------------------


async def test_sign_in_and_separate_accounts(browser, google, connect_as):
    app = await connect_as("atlas_app")
    chatgpt_uid = await app.fetchval(
        "SELECT auth_find_or_create_user($1, 'same@example.test', 'C')", f"oa-{uuid.uuid4()}"
    )
    assert (await browser.get("/auth/session")).json()["sign_in_methods"] == ["openai", "google"]
    resp = await _sign_in(browser, google)
    assert resp.status_code == 302 and resp.headers["location"] == f"{FRONTEND}/atlas"
    assert google.token_form["client_secret"] == "secret"
    user = (await browser.get("/auth/session")).json()["user"]
    assert user["auth_provider"] == "google" and user["email"] == "same@example.test"
    assert user["id"] != str(chatgpt_uid)  # same e-mail, two accounts
    su = await connect_as("atlas")
    providers = await su.fetch(
        "SELECT auth_provider FROM users WHERE email = 'same@example.test' ORDER BY 1"
    )
    assert [r["auth_provider"] for r in providers][-2:] == ["google", "openai"]
    assert (
        await su.fetchval(
            "SELECT count(*) FROM openai_tokens WHERE user_id = $1", uuid.UUID(user["id"])
        )
        == 0
    )


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "someone-else"},
        {"email_verified": False},
        {"iss": "https://evil.test"},
        {"exp": int(time.time()) - 3600},
        {"nonce": "wrong"},
    ],
    ids=["audience", "unverified", "issuer", "expired", "nonce"],
)
async def test_bad_id_token_fails(browser, google, claims):
    resp = await _sign_in(browser, google, **claims)
    assert resp.headers["location"] == f"{FRONTEND}/atlas?auth_error=failed"
    assert COOKIE_NAME not in browser.cookies


async def test_bad_signature_fails(browser, google):
    google.key = OTHER_KEY
    resp = await _sign_in(browser, google)
    assert resp.headers["location"].endswith("auth_error=failed")


async def test_state_checked_and_single_use(browser, google):
    q = await _start(browser, google)
    google.claims = _claims(q["nonce"])
    bad = await browser.get("/auth/google/callback", params={"state": "nope", "code": "c"})
    assert bad.headers["location"].endswith("auth_error=failed")
    q = await _start(browser, google)
    google.claims = _claims(q["nonce"])
    ok = await browser.get("/auth/google/callback", params={"state": q["state"], "code": "c"})
    assert ok.headers["location"] == f"{FRONTEND}/atlas"
    replay = await browser.get("/auth/google/callback", params={"state": q["state"], "code": "c"})
    assert replay.headers["location"].endswith("auth_error=failed")


async def test_pkce_verifier_checked(google):
    tx = google_auth.GoogleTransaction.new(f"{BASE_URL}/auth/google/callback")
    client = google_auth.get_client()
    await client.authorize_url(tx)
    google.challenge = "not-the-challenge"
    google.claims = _claims(tx.nonce)
    with pytest.raises(google_auth.GoogleAuthError):
        await client.exchange_code(tx, "c")


async def test_access_denied(browser, google):
    q = await _start(browser, google)
    resp = await browser.get(
        "/auth/google/callback", params={"state": q["state"], "error": "access_denied"}
    )
    assert resp.headers["location"].endswith("auth_error=denied")


# ---- model access, export, deletion -------------------------------------------------------


async def _google_user(connect_as, app_):
    app = await connect_as("atlas_app")
    sub = f"g-{uuid.uuid4().hex}"
    uid = await app.fetchval(
        "SELECT auth_find_or_create_user('google', $1, 'g@example.test', 'G User')", sub
    )
    c = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_),
        base_url=BASE_URL,
        cookies={COOKIE_NAME: create_session_token(uid)},
    )
    return uid, sub, c


async def test_gateway_choice(app, connect_as, make_user, monkeypatch):
    uid, _, c = await _google_user(connect_as, app)
    await c.aclose()
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_openai_settings.cache_clear()
    with pytest.raises(ApiError) as exc:
        await auth_service.llm_for_user(uid)
    assert exc.value.status_code == 503 and exc.value.code.value == "assistant_unavailable"

    monkeypatch.setenv("OPENAI_API_KEY", "sk-server")
    get_openai_settings.cache_clear()
    llm = await auth_service.llm_for_user(uid)
    assert llm.server_key and await llm.bearer() == "sk-server"
    assert await llm.resolve_model("main") == get_openai_settings().openai_api_model_main

    # A ChatGPT account never falls back to the server key.
    chatgpt = await make_user()
    with pytest.raises(ApiError) as exc:
        await auth_service.llm_for_user(chatgpt.id)
    assert exc.value.code.value == "sign_in_required"
    get_openai_settings.cache_clear()


async def test_agents_sdk_uses_server_key(monkeypatch):
    from backend.llm.agents_sdk import build_agents_model

    monkeypatch.setenv("OPENAI_API_KEY", "sk-server")
    get_openai_settings.cache_clear()
    llm = LLMClient(ServerKeyProvider("sk-server"))
    model = await build_agents_model(llm)
    assert model.model == get_openai_settings().openai_api_model_main
    get_openai_settings.cache_clear()


async def test_rejected_server_key_is_not_reauth():
    def handler(request):
        return httpx.Response(401, json={"error": {"code": "invalid_api_key"}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = LLMClient(ServerKeyProvider("sk-bad"), base_url="http://api.test/v1", http_client=http)
    with pytest.raises(LLMError) as exc:
        await llm.complete_text(instructions="x", input="y")
    assert exc.value.code == "upstream"


async def test_export_and_delete_google_user(app, connect_as):
    uid, sub, c = await _google_user(connect_as, app)
    async with c:
        export = (await c.get("/me/export")).json()
        assert export["account"]["auth_provider"] == "google"
        assert export["account"]["auth_subject"] == sub
        assert export["openai_connected"] is False
        assert (await c.delete("/me")).status_code == 204
    su = await connect_as("atlas")
    assert await su.fetchval("SELECT count(*) FROM users WHERE id = $1", uid) == 0
