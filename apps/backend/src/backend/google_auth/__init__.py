"""Sign in with Google (OpenID Connect authorization code flow with state, nonce and PKCE).

Identity only: scopes `openid email profile`. The ID token is verified (signature against
Google's published keys, issuer, audience, expiry, `email_verified`) and then dropped; Google's
access and refresh tokens are never stored.

When it is offered (`google_login_available`): a client id and secret are configured AND either
a server OpenAI API key (`OPENAI_API_KEY`) is configured or `GOOGLE_LOGIN_ENABLED=true`.

Tests replace the network with `set_http_factory` (an httpx MockTransport); there is no setting
that points this module at a fake Google.
"""

import asyncio
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.openai_auth.oidc import code_challenge, new_code_verifier, new_nonce, new_state

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
SCOPE = "openid email profile"
CALLBACK_PATH = "/auth/google/callback"
_JWKS_TTL_S = 3600.0
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class GoogleSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    google_client_id: str = ""
    google_client_secret: str = ""
    google_login_enabled: bool = False
    # Defaults to <API_URL>/auth/google/callback; must be registered with Google exactly.
    google_redirect_uri: str = ""


@lru_cache
def get_google_settings() -> GoogleSettings:
    return GoogleSettings()


def google_login_available(
    google: GoogleSettings | None = None, server_api_key: str | None = None
) -> bool:
    """Client id and secret configured AND (a server OpenAI API key OR the explicit flag)."""
    if google is None:
        google = get_google_settings()
    if server_api_key is None:
        from backend.openai_auth.settings import get_openai_settings

        server_api_key = get_openai_settings().openai_api_key
    configured = bool(google.google_client_id and google.google_client_secret)
    return configured and (bool(server_api_key) or google.google_login_enabled)


def redirect_uri(google: GoogleSettings | None = None) -> str:
    google = google or get_google_settings()
    if google.google_redirect_uri:
        return google.google_redirect_uri
    from backend.config import get_settings

    return get_settings().api_url.rstrip("/") + CALLBACK_PATH


class GoogleAuthError(Exception):
    """A sign-in failure. `code` is a short machine code; never contains token material."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class GoogleIdentity(BaseModel):
    sub: str
    email: str
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None


@dataclass
class GoogleTransaction:
    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str

    @classmethod
    def new(cls, redirect_uri: str) -> "GoogleTransaction":
        return cls(new_state(), new_nonce(), new_code_verifier(), redirect_uri)


HttpFactory = Callable[[], httpx.AsyncClient]


def _default_http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT)


_http_factory: HttpFactory = _default_http


def set_http_factory(factory: HttpFactory | None) -> None:
    """Tests only: route Google's endpoints through a fake transport (None restores)."""
    global _http_factory
    _http_factory = factory or _default_http
    _cache.clear()


def _str_claim(claims: dict[str, Any], key: str) -> str | None:
    value = claims.get(key)
    return (value.strip() or None) if isinstance(value, str) else None


class GoogleOIDC:
    def __init__(self, settings: GoogleSettings):
        self.settings = settings
        self._discovery: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None
        self._jwks_at = 0.0
        self._lock = asyncio.Lock()

    async def _get(self, url: str) -> httpx.Response:
        try:
            async with _http_factory() as client:
                return await client.get(url)
        except httpx.HTTPError as exc:
            raise GoogleAuthError("network_error", type(exc).__name__) from None

    async def discovery(self) -> dict[str, Any]:
        if self._discovery is None:
            async with self._lock:
                if self._discovery is None:
                    resp = await self._get(GOOGLE_DISCOVERY_URL)
                    try:
                        data = resp.json() if resp.status_code == 200 else None
                    except ValueError:
                        data = None
                    keys = ("authorization_endpoint", "token_endpoint", "jwks_uri")
                    if not isinstance(data, dict) or not all(data.get(k) for k in keys):
                        raise GoogleAuthError("discovery_failed")
                    self._discovery = data
        return self._discovery

    async def authorize_url(self, tx: GoogleTransaction) -> str:
        disc = await self.discovery()
        params = {
            "client_id": self.settings.google_client_id,
            "response_type": "code",
            "redirect_uri": tx.redirect_uri,
            "scope": SCOPE,
            "state": tx.state,
            "nonce": tx.nonce,
            "code_challenge": code_challenge(tx.code_verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return f"{disc['authorization_endpoint']}?{urlencode(params)}"

    async def exchange_code(self, tx: GoogleTransaction, code: str) -> GoogleIdentity:
        """Exchange the code (with the PKCE verifier) and verify the ID token. Google's access
        token is discarded unused."""
        disc = await self.discovery()
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": tx.code_verifier,
            "redirect_uri": tx.redirect_uri,
            "client_id": self.settings.google_client_id,
            "client_secret": self.settings.google_client_secret,
        }
        try:
            async with _http_factory() as client:
                resp = await client.post(
                    disc["token_endpoint"], data=form, headers={"Accept": "application/json"}
                )
        except httpx.HTTPError as exc:
            raise GoogleAuthError("network_error", type(exc).__name__) from None
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code != 200 or not isinstance(data, dict):
            code_ = data.get("error") if isinstance(data, dict) else None
            raise GoogleAuthError(str(code_ or "token_request_failed")[:40])
        id_token = data.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise GoogleAuthError("missing_id_token")
        return await self.verify_id_token(id_token, nonce=tx.nonce)

    async def _keys(self, *, force: bool) -> list[dict[str, Any]]:
        if self._jwks is None or force or time.time() - self._jwks_at > _JWKS_TTL_S:
            disc = await self.discovery()
            resp = await self._get(disc["jwks_uri"])
            try:
                jwks = resp.json() if resp.status_code == 200 else None
            except ValueError:
                jwks = None
            if not isinstance(jwks, dict):
                raise GoogleAuthError("jwks_failed")
            self._jwks, self._jwks_at = jwks, time.time()
        return list(self._jwks.get("keys") or [])

    async def _signing_key(self, kid: str | None) -> Any:
        if not kid:
            raise GoogleAuthError("invalid_id_token", "no kid")
        for force in (False, True):
            for raw in await self._keys(force=force):
                if raw.get("kid") == kid:
                    return jwt.PyJWK(raw).key
        raise GoogleAuthError("invalid_id_token", "unknown signing key")

    async def verify_id_token(self, id_token: str, *, nonce: str) -> GoogleIdentity:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError:
            raise GoogleAuthError("invalid_id_token", "malformed") from None
        if header.get("alg") != "RS256":
            raise GoogleAuthError("invalid_id_token", "alg")
        key = await self._signing_key(header.get("kid"))
        try:
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=["RS256"],
                audience=self.settings.google_client_id,
                leeway=60,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError:
            raise GoogleAuthError("invalid_id_token", "expired") from None
        except jwt.InvalidAudienceError:
            raise GoogleAuthError("invalid_id_token", "audience") from None
        except jwt.InvalidSignatureError:
            raise GoogleAuthError("invalid_id_token", "signature") from None
        except jwt.PyJWTError as exc:
            raise GoogleAuthError("invalid_id_token", type(exc).__name__) from None
        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise GoogleAuthError("invalid_id_token", "issuer")
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise GoogleAuthError("invalid_id_token", "nonce")
        azp = claims.get("azp")
        if azp and azp != self.settings.google_client_id:
            raise GoogleAuthError("invalid_id_token", "azp")
        email = _str_claim(claims, "email")
        if not email or claims.get("email_verified") is not True:
            raise GoogleAuthError("email_unverified")
        return GoogleIdentity(
            sub=str(claims["sub"]),
            email=email,
            name=_str_claim(claims, "name"),
            given_name=_str_claim(claims, "given_name"),
            family_name=_str_claim(claims, "family_name"),
        )


_cache: dict[tuple[str, str], GoogleOIDC] = {}


def get_client() -> GoogleOIDC:
    s = get_google_settings()
    key = (s.google_client_id, s.google_client_secret)
    if key not in _cache:
        _cache.clear()
        _cache[key] = GoogleOIDC(s)
    return _cache[key]


__all__ = [
    "CALLBACK_PATH",
    "SCOPE",
    "GoogleAuthError",
    "GoogleIdentity",
    "GoogleOIDC",
    "GoogleSettings",
    "GoogleTransaction",
    "get_client",
    "get_google_settings",
    "google_login_available",
    "redirect_uri",
    "set_http_factory",
]
