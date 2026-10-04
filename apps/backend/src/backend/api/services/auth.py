"""Sign in with ChatGPT for the web app (OIDC + PKCE, dynamic registration or partner client),
OpenAI token storage, and the per-user LLM client (own ChatGPT plan, or the server key for
accounts from another sign-in; see `llm_for_user`).

Tokens are stored Fernet-encrypted in `openai_tokens` under RLS and never leave the server; they
never appear in logs, URLs or error messages. Failures redirect to the frontend with only a short
code (`?auth_error=denied|failed`).
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import jwt
from fastapi import Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import require_user
from backend.api.errors import ApiError
from backend.api.security import clear_session, issue_session
from backend.config import get_settings
from backend.db.session import set_user, user_transaction
from backend.llm import LLMClient, LLMError, ServerKeyProvider
from backend.observability import get_tracer
from backend.openai_auth import (
    DYNAMIC_CLIENT_ID,
    AuthTransaction,
    OAuthError,
    OIDCClient,
    TokenCryptoError,
    TokenSet,
    decrypt,
    encrypt,
    get_openai_settings,
    is_issued_client_id,
    validate_loopback_redirect,
)
from backend.schemas.account import CurrentUser
from backend.schemas.enums import ErrorCode

log = logging.getLogger(__name__)

TX_COOKIE = "amber_oauth_tx"
CLIENT_COOKIE = "amber_oai_client"
TX_TTL_S = 600
CLIENT_COOKIE_TTL_S = 365 * 24 * 3600
_REVOKE_TIMEOUT_S = 5.0

_used_states: dict[str, float] = {}
_oidc_cache: dict[tuple, OIDCClient] = {}


# ---- helpers ------------------------------------------------------------------------------


def _oidc() -> OIDCClient:
    s = get_openai_settings()
    key = (s.issuer, s.openai_client_id, s.openai_client_secret, s.api_base_url, s.openai_scope)
    if key not in _oidc_cache:
        _oidc_cache.clear()
        _oidc_cache[key] = OIDCClient(s)
    return _oidc_cache[key]


def host_id() -> str:
    """Stable ext_agent_host_id: OPENAI_AGENT_HOST_ID, else derived from server config."""
    s = get_openai_settings()
    if s.openai_agent_host_id:
        return s.openai_agent_host_id
    seed = f"{get_settings().api_url}|{get_settings().session_secret}".encode()
    return f"urn:uuid:{uuid.UUID(bytes=hashlib.sha256(seed).digest()[:16], version=4)}"


def safe_return_to(value: str | None) -> str:
    """Only same-site relative paths ("/path?query"); anything else becomes "/"."""
    if not value or len(value) > 512 or not value.startswith("/"):
        return "/"
    if value.startswith(("//", "/\\")) or any(c in value for c in "\\\r\n\t\x00"):
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return "/"
    return value


def _frontend(path: str, **query: str) -> str:
    base = get_settings().frontend_url.rstrip("/")
    if not query:
        return base + path
    sep = "&" if "?" in path else "?"
    return f"{base}{path}{sep}{urlencode(query)}"


def _cookie_args(max_age: int, path: str = "/") -> dict[str, Any]:
    return {
        "max_age": max_age,
        "httponly": True,
        "secure": get_settings().cookie_secure,
        "samesite": "lax",
        "path": path,
    }


def _seal(payload: dict[str, Any]) -> str:
    return encrypt(json.dumps(payload, separators=(",", ":"))).decode("ascii")


def _unseal(value: str | None, ttl: int) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        data = json.loads(decrypt(value, ttl=ttl))
    except (TokenCryptoError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _remembered_client(request: Request) -> str | None:
    data = _unseal(request.cookies.get(CLIENT_COOKIE), CLIENT_COOKIE_TTL_S)
    cid = data.get("client_id") if data else None
    return cid if is_issued_client_id(cid) else None


def _fail(code: str = "failed", return_to: str = "/") -> RedirectResponse:
    resp = RedirectResponse(_frontend(return_to, auth_error=code), status_code=302)
    resp.delete_cookie(TX_COOKIE, path="/auth")
    return resp


def _mark_state_used(state: str) -> bool:
    now = time.time()
    for s, exp in list(_used_states.items()):
        if exp < now:
            _used_states.pop(s, None)
    if state in _used_states:
        return False
    _used_states[state] = now + TX_TTL_S
    return True


async def _authorize_redirect(return_to: str, client_id: str, *, retry: bool) -> Response:
    settings = get_openai_settings()
    oidc = _oidc()
    redirect_uri = settings.openai_redirect_uri
    if not settings.partner_mode:
        validate_loopback_redirect(redirect_uri)
    discovery = await oidc.discovery()
    tx = AuthTransaction.new(redirect_uri=redirect_uri, client_id=client_id)
    url = oidc.authorize_url(discovery, tx, ext_agent_host_id=host_id())
    sealed = _seal(
        {
            "state": tx.state,
            "nonce": tx.nonce,
            "verifier": tx.code_verifier,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "return_to": return_to,
            "retry": retry,
        }
    )
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(TX_COOKIE, sealed, **_cookie_args(TX_TTL_S, path="/auth"))
    return resp


# ---- routes -------------------------------------------------------------------------------


def chatgpt_login_available() -> bool:
    """Partner mode (OPENAI_CLIENT_ID set), or API and frontend on loopback: the local flow only
    accepts a 127.0.0.1 redirect, so on a hosted domain without a partner client it cannot work."""
    return get_openai_settings().partner_mode or get_settings().is_local


async def start(request: Request, return_to: str | None) -> Response:
    """Create state/nonce/PKCE, keep them in a short-lived sealed cookie, redirect to OpenAI."""
    if not chatgpt_login_available():
        raise ApiError(404, ErrorCode.not_found, "ChatGPT sign-in is not available here.")
    target = safe_return_to(return_to)
    try:
        client_id = _oidc().default_client_id(_remembered_client(request))
        return await _authorize_redirect(target, client_id, retry=False)
    except (OAuthError, TokenCryptoError, ValueError) as exc:
        log.error("sign-in start failed: %s", type(exc).__name__)
        return _fail("failed", target)


async def callback(request: Request, db: AsyncSession) -> Response:
    """Validate state, exchange the code, verify the ID token, store tokens, set the session."""
    params = request.query_params
    tx = _unseal(request.cookies.get(TX_COOKIE), TX_TTL_S)
    if tx is None:
        return _fail("failed")
    return_to = safe_return_to(tx.get("return_to"))
    state = params.get("state") or ""
    if not state or state != tx.get("state") or not _mark_state_used(state):
        return _fail("failed", return_to)

    client_id = str(tx.get("client_id") or "")
    settings = get_openai_settings()
    remembered = (
        client_id
        if is_issued_client_id(client_id) and client_id != settings.openai_client_id
        else None
    )

    async def restart_dynamic() -> Response:
        resp = await _authorize_redirect(return_to, DYNAMIC_CLIENT_ID, retry=True)
        resp.delete_cookie(CLIENT_COOKIE, path="/")
        return resp

    error = params.get("error")
    if error:
        if error == "access_denied":
            return _fail("denied", return_to)
        if remembered and not tx.get("retry"):
            return await restart_dynamic()
        log.info("sign-in callback error: %s", error[:40])
        return _fail("failed", return_to)

    code = params.get("code")
    if not code:
        return _fail("failed", return_to)
    issued = params.get("client_id") if client_id == DYNAMIC_CLIENT_ID else client_id
    if not issued or issued == DYNAMIC_CLIENT_ID:
        return _fail("failed", return_to)

    auth_tx = AuthTransaction(
        state=tx["state"],
        nonce=tx["nonce"],
        code_verifier=tx["verifier"],
        redirect_uri=tx["redirect_uri"],
        client_id=client_id,
    )
    try:
        tokens, claims = await _oidc().exchange_code(auth_tx, code, client_id=issued)
    except OAuthError as exc:
        if remembered and not tx.get("retry") and exc.code in ("invalid_client", "invalid_grant"):
            return await restart_dynamic()
        log.warning("sign-in code exchange failed: %s", exc.code)
        return _fail("failed", return_to)

    try:
        uid = await db.scalar(
            text("SELECT auth_find_or_create_user('openai', :sub, :email, :name)"),
            {"sub": claims.sub, "email": claims.email, "name": claims.name},
        )
        await set_user(db, uid)
        await _store_tokens(db, uid, tokens)
    except TokenCryptoError:
        log.error("TOKEN_ENCRYPTION_KEY missing or invalid")
        return _fail("failed", return_to)

    resp = RedirectResponse(_frontend(return_to), status_code=302)
    resp.delete_cookie(TX_COOKIE, path="/auth")
    issue_session(resp, uid)
    if not settings.partner_mode:
        resp.set_cookie(
            CLIENT_COOKIE, _seal({"client_id": issued}), **_cookie_args(CLIENT_COOKIE_TTL_S)
        )
    return resp


async def logout(db: AsyncSession, user: CurrentUser | None, response: Response) -> None:
    """Revoke the refresh token (best effort), delete stored tokens, clear the session cookie."""
    clear_session(response)
    if user is None:
        return
    tokens = await _load_tokens(db, user.id)
    if tokens is not None:
        try:
            await asyncio.wait_for(_oidc().revoke(tokens), _REVOKE_TIMEOUT_S)
        except Exception as exc:
            log.info("token revocation not confirmed: %s", type(exc).__name__)
    await db.execute(text("DELETE FROM openai_tokens WHERE user_id = :uid"), {"uid": user.id})


# ---- token storage ------------------------------------------------------------------------

_UPSERT_SQL = text(
    """
    INSERT INTO openai_tokens (user_id, client_id, access_token_enc, refresh_token_enc,
                               id_token_enc, expires_at, scopes, updated_at)
    VALUES (:uid, :client_id, :access, :refresh, :id_token, :expires_at, :scopes, now())
    ON CONFLICT (user_id) DO UPDATE SET
        client_id = EXCLUDED.client_id, access_token_enc = EXCLUDED.access_token_enc,
        refresh_token_enc = EXCLUDED.refresh_token_enc, id_token_enc = EXCLUDED.id_token_enc,
        expires_at = EXCLUDED.expires_at, scopes = EXCLUDED.scopes, updated_at = now()
    """
)
_SELECT_SQL = (
    "SELECT client_id, access_token_enc, refresh_token_enc, id_token_enc, expires_at, scopes,"
    " updated_at"
    " FROM openai_tokens WHERE user_id = :uid"
)


def _enc(value: str | None) -> str | None:
    return encrypt(value).decode("ascii") if value else None


def _dec(value: str | None) -> str | None:
    return decrypt(value) if value else None


async def _store_tokens(db: AsyncSession, uid: UUID, tokens: TokenSet) -> None:
    await db.execute(
        _UPSERT_SQL,
        {
            "uid": uid,
            "client_id": tokens.client_id,
            "access": _enc(tokens.access_token),
            "refresh": _enc(tokens.refresh_token),
            "id_token": _enc(tokens.id_token),
            "expires_at": tokens.expires_at,
            "scopes": tokens.scopes,
        },
    )


async def _load_tokens(db: AsyncSession, uid: UUID, *, for_update: bool = False) -> TokenSet | None:
    sql = _SELECT_SQL + (" FOR UPDATE" if for_update else "")
    row = (await db.execute(text(sql), {"uid": uid})).mappings().first()
    if row is None or not row["access_token_enc"]:
        return None
    try:
        return TokenSet(
            access_token=_dec(row["access_token_enc"]) or "",
            refresh_token=_dec(row["refresh_token_enc"]),
            id_token=_dec(row["id_token_enc"]),
            expires_at=row["expires_at"] or datetime.now(UTC),
            scopes=list(row["scopes"] or []),
            issued_at=row["updated_at"],
            client_id=row["client_id"] or "",
        )
    except TokenCryptoError:
        log.error("stored OpenAI tokens could not be decrypted")
        return None


async def stored_name_claims(db: AsyncSession, uid: UUID) -> tuple[str | None, str | None]:
    """`given_name` and `family_name` from the stored ID token, or (None, None).

    The token was validated at sign-in and is decrypted here in memory only; nothing read from
    it is stored. Used for the work-details name prefill.
    """
    enc = await db.scalar(
        text("SELECT id_token_enc FROM openai_tokens WHERE user_id = :uid"), {"uid": uid}
    )
    if not enc:
        return None, None
    try:
        claims = jwt.decode(_dec(enc) or "", options={"verify_signature": False})
    except (TokenCryptoError, jwt.PyJWTError, ValueError):
        return None, None

    def claim(key: str) -> str | None:
        value = claims.get(key)
        return (value.strip() or None) if isinstance(value, str) else None

    return claim("given_name"), claim("family_name")


# ---- per-user LLM client --------------------------------------------------------------------


class DbTokenProvider:
    """TokenProvider over `openai_tokens`. Each access runs in its own short RLS transaction;
    refreshes lock the row (SELECT ... FOR UPDATE) so concurrent requests rotate only once."""

    def __init__(self, user_id: UUID, tokens: TokenSet | None = None):
        self.user_id = user_id
        self._tokens = tokens
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return f"DbTokenProvider(user_id={self.user_id})"

    async def get_token(self) -> str:
        tokens = self._tokens
        if tokens is not None and not tokens.needs_refresh():
            return tokens.access_token
        return await self._refresh(force=False)

    async def force_refresh(self) -> str:
        return await self._refresh(force=True)

    async def _refresh(self, *, force: bool) -> str:
        async with self._lock:
            stale = self._tokens.access_token if self._tokens else None
            dead = False
            async with user_transaction(self.user_id) as db:
                tokens = await _load_tokens(db, self.user_id, for_update=True)
                if tokens is None or not tokens.has_plan_usage:
                    raise LLMError("reauth_required", "no usable OpenAI sign-in")
                rotated_elsewhere = force and stale is not None and tokens.access_token != stale
                if rotated_elsewhere or (not force and not tokens.needs_refresh()):
                    self._tokens = tokens
                    return tokens.access_token
                try:
                    tokens = await _oidc().refresh(tokens)
                except OAuthError as exc:
                    if not (exc.reauth_required or exc.code == "invalid_client"):
                        raise LLMError("upstream", f"token refresh failed ({exc})") from None
                    dead = True
                    await db.execute(
                        text("DELETE FROM openai_tokens WHERE user_id = :uid"),
                        {"uid": self.user_id},
                    )
                else:
                    await _store_tokens(db, self.user_id, tokens)
            if dead:
                self._tokens = None
                raise LLMError("reauth_required", "OpenAI sign-in expired")
            self._tokens = tokens
            return tokens.access_token


async def _auth_provider(user_id: UUID) -> str | None:
    """The account's sign-in provider ("openai" or "google"); it never changes for an id."""
    provider = _providers.get(user_id)
    if provider is None:
        async with user_transaction(user_id) as db:
            provider = await db.scalar(
                text("SELECT auth_provider FROM users WHERE id = :uid"), {"uid": user_id}
            )
        if provider is not None:
            if len(_providers) > 10_000:
                _providers.clear()
            _providers[user_id] = provider
    return provider


_providers: dict[UUID, str] = {}


async def uses_server_key(user_id: UUID) -> bool:
    """True when this account's model calls run on the operator's OPENAI_API_KEY (the same
    choice as `llm_for_user`); ChatGPT accounts use their own plan."""
    provider = await _auth_provider(user_id)
    return (
        provider is not None and provider != "openai" and bool(get_openai_settings().openai_api_key)
    )


async def llm_for_user(user_id: UUID) -> LLMClient:
    """The model gateway for this user (services, SSE handlers, background jobs).

    - ChatGPT accounts: billed to the user's own ChatGPT plan, as always. Uses its own short
      RLS transactions; refreshes tokens with row locking when due. ApiError 401
      `sign_in_required` when there is no usable OpenAI sign-in (no tokens, no plan-usage scope,
      or the refresh failed); later calls raise LLMError("reauth_required") if it dies mid-way.
    - Other accounts (Google): the server OpenAI API key (`OPENAI_API_KEY`) when configured,
      else ApiError 503 `assistant_unavailable`.
    """
    provider = await _auth_provider(user_id)
    if provider is not None and provider != "openai":
        api_key = get_openai_settings().openai_api_key
        if not api_key:
            raise ApiError(503, ErrorCode.assistant_unavailable)
        return LLMClient(ServerKeyProvider(api_key), tracer=get_tracer())
    plan = DbTokenProvider(user_id)
    try:
        await plan.get_token()
    except LLMError as exc:
        if exc.code == "reauth_required":
            raise ApiError(401, ErrorCode.sign_in_required) from None
        raise ApiError(502, ErrorCode.upstream_error) from None
    return LLMClient(plan, tracer=get_tracer())


async def get_user_llm(user: Annotated[CurrentUser, Depends(require_user)]) -> LLMClient:
    """FastAPI dependency: the signed-in user's LLMClient; 401 sign_in_required otherwise."""
    return await llm_for_user(user.id)


UserLLM = Annotated[LLMClient, Depends(get_user_llm)]
