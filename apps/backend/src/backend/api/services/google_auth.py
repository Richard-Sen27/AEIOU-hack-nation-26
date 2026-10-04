"""Sign in with Google for the web app: OIDC authorization code flow with state, nonce and PKCE.

Offered only when `google_login_available()` holds; otherwise both routes answer 404. The
per-attempt values live in a short-lived sealed cookie (as for ChatGPT). Only the identity is
kept (provider "google", subject, e-mail, name); Google's tokens are never stored. Accounts are
never merged by e-mail: a Google account is its own account. Failures redirect to the frontend
with only `?auth_error=denied|failed`.
"""

import logging

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.api.security import issue_session
from backend.api.services.auth import (
    TX_TTL_S,
    _cookie_args,
    _frontend,
    _mark_state_used,
    _seal,
    _unseal,
    chatgpt_login_available,
    safe_return_to,
)
from backend.db.session import set_user
from backend.google_auth import (
    GoogleAuthError,
    GoogleTransaction,
    get_client,
    google_login_available,
    redirect_uri,
)
from backend.openai_auth import TokenCryptoError
from backend.schemas.enums import AuthProvider, ErrorCode

log = logging.getLogger(__name__)

TX_COOKIE = "amber_google_tx"
TX_COOKIE_PATH = "/auth/google"


def sign_in_methods() -> list[AuthProvider]:
    """What /auth/session tells the frontend: ChatGPT only where it can work (loopback or
    partner mode), Google only when enabled."""
    methods = [AuthProvider.openai] if chatgpt_login_available() else []
    if google_login_available():
        methods.append(AuthProvider.google)
    return methods


def _require_enabled() -> None:
    if not google_login_available():
        raise ApiError(404, ErrorCode.not_found, "Google sign-in is not enabled.")


def _fail(code: str = "failed", return_to: str = "/") -> RedirectResponse:
    resp = RedirectResponse(_frontend(return_to, auth_error=code), status_code=302)
    resp.delete_cookie(TX_COOKIE, path=TX_COOKIE_PATH)
    return resp


async def start(return_to: str | None) -> Response:
    """Create state, nonce and PKCE verifier, keep them sealed in a cookie, redirect to Google."""
    _require_enabled()
    target = safe_return_to(return_to)
    tx = GoogleTransaction.new(redirect_uri())
    try:
        url = await get_client().authorize_url(tx)
        sealed = _seal(
            {
                "state": tx.state,
                "nonce": tx.nonce,
                "verifier": tx.code_verifier,
                "redirect_uri": tx.redirect_uri,
                "return_to": target,
            }
        )
    except (GoogleAuthError, TokenCryptoError) as exc:
        log.error("google sign-in start failed: %s", type(exc).__name__)
        return _fail("failed", target)
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(TX_COOKIE, sealed, **_cookie_args(TX_TTL_S, path=TX_COOKIE_PATH))
    return resp


async def callback(request: Request, db: AsyncSession) -> Response:
    """Check state, exchange the code with the verifier, verify the ID token, set the session."""
    _require_enabled()
    params = request.query_params
    tx = _unseal(request.cookies.get(TX_COOKIE), TX_TTL_S)
    if tx is None:
        return _fail("failed")
    return_to = safe_return_to(tx.get("return_to"))
    state = params.get("state") or ""
    if not state or state != tx.get("state") or not _mark_state_used(state):
        return _fail("failed", return_to)
    error = params.get("error")
    if error:
        if error == "access_denied":
            return _fail("denied", return_to)
        log.info("google sign-in callback error: %s", error[:40])
        return _fail("failed", return_to)
    code = params.get("code")
    if not code:
        return _fail("failed", return_to)

    google_tx = GoogleTransaction(
        state=tx["state"],
        nonce=tx["nonce"],
        code_verifier=tx["verifier"],
        redirect_uri=tx["redirect_uri"],
    )
    try:
        identity = await get_client().exchange_code(google_tx, code)
    except GoogleAuthError as exc:
        log.warning("google sign-in failed: %s", exc.code)
        return _fail("failed", return_to)

    uid = await db.scalar(
        text("SELECT auth_find_or_create_user('google', :sub, :email, :name)"),
        {"sub": identity.sub, "email": identity.email, "name": identity.name},
    )
    await set_user(db, uid)
    resp = RedirectResponse(_frontend(return_to), status_code=302)
    resp.delete_cookie(TX_COOKIE, path=TX_COOKIE_PATH)
    issue_session(resp, uid)
    return resp
