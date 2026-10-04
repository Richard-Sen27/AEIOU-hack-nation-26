"""OpenID Connect + PKCE client for Sign in with ChatGPT (dynamic registration or partner)."""

import asyncio
import base64
import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from pydantic import BaseModel

from backend.openai_auth.settings import OpenAISettings, get_openai_settings
from backend.openai_auth.tokens import TokenSet

DYNAMIC_CLIENT_ID = "dynamic_agent_client"
PLAN_SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PARTNER_SCOPE = "openid profile email"
CALLBACK_PATH = "/auth/callback"

# Refresh failures that mean "these tokens are dead, sign in again".
UNUSABLE_TOKEN_ERRORS = frozenset(
    {
        "invalid_grant",
        "invalid_refresh_token",
        "token_expired",
        "refresh_token_expired",
        "refresh_token_invalidated",
        "refresh_token_reused",
    }
)

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class OAuthError(Exception):
    """An OAuth/OIDC failure. `code` is a short machine code; never contains token material."""

    def __init__(self, code: str, message: str = "", *, status: int | None = None):
        self.code = code
        self.status = status
        super().__init__(f"{code}: {message}" if message else code)

    @property
    def reauth_required(self) -> bool:
        return self.code in UNUSABLE_TOKEN_ERRORS


class Discovery(BaseModel):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    revocation_endpoint: str | None = None


class IdentityClaims(BaseModel):
    sub: str
    email: str | None = None
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    email_verified: bool | None = None
    raw: dict[str, Any] = {}


def _str_claim(claims: dict[str, Any], key: str) -> str | None:
    """An optional string claim (OIDC standard claims such as given_name); None otherwise."""
    value = claims.get(key)
    return (value.strip() or None) if isinstance(value, str) else None


def new_state() -> str:
    return secrets.token_urlsafe(32)


def new_nonce() -> str:
    return secrets.token_urlsafe(32)


def new_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:96]


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_host_id() -> str:
    return f"urn:uuid:{uuid.uuid4()}"


def is_issued_client_id(client_id: str | None) -> bool:
    return bool(client_id) and client_id != DYNAMIC_CLIENT_ID


def validate_loopback_redirect(uri: str) -> None:
    """Enforce OpenAI's rule for the dynamic flow: http://127.0.0.1:<port>/auth/callback."""
    parts = urlsplit(uri)
    if parts.scheme != "http" or parts.hostname != "127.0.0.1" or parts.path != CALLBACK_PATH:
        raise ValueError("redirect URI must be http://127.0.0.1:<port>/auth/callback")


@dataclass
class AuthTransaction:
    """Per-attempt values the caller must keep (server-side or in a signed cookie)."""

    state: str
    nonce: str
    code_verifier: str
    redirect_uri: str
    client_id: str
    created_at: float = field(default_factory=time.time)

    @classmethod
    def new(cls, *, redirect_uri: str, client_id: str) -> "AuthTransaction":
        return cls(new_state(), new_nonce(), new_code_verifier(), redirect_uri, client_id)


class OIDCClient:
    def __init__(
        self,
        settings: OpenAISettings | None = None,
        *,
        http: httpx.AsyncClient | None = None,
    ):
        self.settings = settings or get_openai_settings()
        self._http = http
        self._discovery: Discovery | None = None
        self._jwks: dict[str, Any] | None = None
        self._jwks_fetched_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def mode(self) -> Literal["dynamic", "partner"]:
        return "partner" if self.settings.partner_mode else "dynamic"

    @property
    def scope(self) -> str:
        if self.settings.openai_scope:
            return self.settings.openai_scope
        return PARTNER_SCOPE if self.settings.partner_mode else PLAN_SCOPE

    def default_client_id(self, remembered: str | None = None) -> str:
        if self.settings.openai_client_id:
            return self.settings.openai_client_id
        return remembered if is_issued_client_id(remembered) else DYNAMIC_CLIENT_ID

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            if self._http is not None:
                return await self._http.request(method, url, **kwargs)
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                return await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise OAuthError("network_error", type(exc).__name__) from None

    async def discovery(self) -> Discovery:
        if self._discovery is None:
            async with self._lock:
                if self._discovery is None:
                    self._discovery = await self._fetch_discovery()
        return self._discovery

    async def _fetch_discovery(self) -> Discovery:
        issuer = self.settings.issuer
        resp = await self._request("GET", f"{issuer}/.well-known/openid-configuration")
        if resp.status_code != 200:
            raise OAuthError(
                "discovery_failed", f"HTTP {resp.status_code}", status=resp.status_code
            )
        try:
            return Discovery.model_validate(resp.json())
        except (ValueError, json.JSONDecodeError):
            raise OAuthError("discovery_failed", "invalid document") from None

    def authorize_url(
        self,
        discovery: Discovery,
        tx: AuthTransaction,
        *,
        ext_agent_host_id: str | None = None,
        agent_name_hint: str | None = None,
        id_token_hint: str | None = None,
        login_hint: str | None = None,
    ) -> str:
        params: dict[str, str] = {
            "client_id": tx.client_id,
            "response_type": "code",
            "redirect_uri": tx.redirect_uri,
            "scope": self.scope,
            "state": tx.state,
            "nonce": tx.nonce,
            "code_challenge": code_challenge(tx.code_verifier),
            "code_challenge_method": "S256",
        }
        if self.mode == "dynamic":
            if not ext_agent_host_id:
                raise ValueError("ext_agent_host_id is required for the dynamic flow")
            params["resource"] = self.settings.resource
            params["ext_agent_host_id"] = ext_agent_host_id
            if tx.client_id == DYNAMIC_CLIENT_ID:
                params["agent_name_hint"] = agent_name_hint or self.settings.openai_agent_name
        if id_token_hint and tx.client_id != DYNAMIC_CLIENT_ID:
            params["id_token_hint"] = id_token_hint
        if login_hint:
            params["login_hint"] = login_hint
        return f"{discovery.authorization_endpoint}?{urlencode(params)}"

    def _client_auth(self, client_id: str) -> tuple[dict[str, str], httpx.BasicAuth | None]:
        """Partner confidential clients use client_secret_basic; dynamic clients are public."""
        secret = self.settings.openai_client_secret
        if secret and client_id == self.settings.openai_client_id:
            return {}, httpx.BasicAuth(client_id, secret)
        return {"client_id": client_id}, None

    async def _token_request(self, form: dict[str, str], client_id: str) -> dict[str, Any]:
        disc = await self.discovery()
        extra, auth = self._client_auth(client_id)
        resp = await self._request(
            "POST",
            disc.token_endpoint,
            data={**form, **extra},
            auth=auth,
            headers={"Accept": "application/json"},
        )
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code != 200 or "access_token" not in data:
            code = data.get("error") if isinstance(data, dict) else None
            if isinstance(code, dict):
                code = code.get("code") or code.get("type")
            raise OAuthError(str(code or "token_request_failed"), status=resp.status_code)
        return data

    async def exchange_code(
        self, tx: AuthTransaction, code: str, *, client_id: str | None = None
    ) -> tuple[TokenSet, IdentityClaims]:
        """Exchange the code, validate the ID token. `client_id` = issued id from the callback."""
        cid = client_id or tx.client_id
        if cid == DYNAMIC_CLIENT_ID:
            raise OAuthError("missing_issued_client_id")
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": tx.code_verifier,
            "redirect_uri": tx.redirect_uri,
        }
        if self.mode == "dynamic":
            form["resource"] = self.settings.resource
        data = await self._token_request(form, cid)
        tokens = TokenSet.from_token_response(data, client_id=cid)
        if not tokens.id_token:
            raise OAuthError("missing_id_token")
        claims = await self.validate_id_token(tokens.id_token, client_id=cid, nonce=tx.nonce)
        return tokens, claims

    async def refresh(self, tokens: TokenSet) -> TokenSet:
        if not tokens.refresh_token:
            raise OAuthError("invalid_grant", "no refresh token")
        form = {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token}
        if self.mode == "dynamic":
            form["resource"] = self.settings.resource
        data = await self._token_request(form, tokens.client_id)
        return TokenSet.from_token_response(data, client_id=tokens.client_id, previous=tokens)

    async def revoke(self, tokens: TokenSet) -> bool:
        """Revoke the refresh token. Returns True if the server confirmed it."""
        token = tokens.refresh_token or tokens.access_token
        hint = "refresh_token" if tokens.refresh_token else "access_token"
        try:
            disc = await self.discovery()
        except OAuthError:
            return False
        if not disc.revocation_endpoint:
            return False
        extra, auth = self._client_auth(tokens.client_id)
        try:
            resp = await self._request(
                "POST",
                disc.revocation_endpoint,
                data={"token": token, "token_type_hint": hint, **extra},
                auth=auth,
            )
        except OAuthError:
            return False
        return resp.status_code == 200

    async def _jwks_keys(self, *, force: bool = False) -> dict[str, Any]:
        if self._jwks is None or force or time.time() - self._jwks_fetched_at > 3600:
            disc = await self.discovery()
            resp = await self._request("GET", disc.jwks_uri)
            if resp.status_code != 200:
                raise OAuthError("jwks_failed", f"HTTP {resp.status_code}")
            self._jwks = resp.json()
            self._jwks_fetched_at = time.time()
        return self._jwks

    async def _signing_key(self, kid: str | None) -> Any:
        for force in (False, True):
            jwks = await self._jwks_keys(force=force)
            keys = jwks.get("keys", [])
            for raw in keys:
                if kid is None or raw.get("kid") == kid:
                    return jwt.PyJWK(raw).key
            if kid is None:
                break
        raise OAuthError("invalid_id_token", "unknown signing key")

    async def validate_id_token(
        self, id_token: str, *, client_id: str, nonce: str | None
    ) -> IdentityClaims:
        disc = await self.discovery()
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError:
            raise OAuthError("invalid_id_token", "malformed") from None
        alg = header.get("alg")
        if alg not in ("RS256", "RS384", "RS512", "ES256", "ES384", "PS256"):
            raise OAuthError("invalid_id_token", "unsupported alg")
        key = await self._signing_key(header.get("kid"))
        try:
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=[alg],
                audience=client_id,
                issuer=disc.issuer,
                leeway=60,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError:
            raise OAuthError("invalid_id_token", "expired") from None
        except jwt.InvalidAudienceError:
            raise OAuthError("invalid_id_token", "audience") from None
        except jwt.InvalidIssuerError:
            raise OAuthError("invalid_id_token", "issuer") from None
        except jwt.InvalidSignatureError:
            raise OAuthError("invalid_id_token", "signature") from None
        except jwt.PyJWTError as exc:
            raise OAuthError("invalid_id_token", type(exc).__name__) from None
        if nonce is not None and not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise OAuthError("invalid_id_token", "nonce")
        azp = claims.get("azp")
        if azp and azp != client_id:
            raise OAuthError("invalid_id_token", "azp")
        return IdentityClaims(
            sub=str(claims["sub"]),
            email=claims.get("email"),
            name=claims.get("name"),
            given_name=_str_claim(claims, "given_name"),
            family_name=_str_claim(claims, "family_name"),
            email_verified=claims.get("email_verified"),
            raw=claims,
        )
