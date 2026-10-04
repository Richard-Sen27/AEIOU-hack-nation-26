"""Sign-in routes: ChatGPT (OIDC + PKCE; dynamic registration or partner client) and, when
enabled, Google (OIDC + PKCE, identity only)."""

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse

from backend.api.deps import DB, OptionalUser
from backend.api.services import auth, google_auth

router = APIRouter(tags=["auth"])


@router.get(
    "/auth/chatgpt/start",
    response_class=RedirectResponse,
    status_code=302,
    operation_id="authStart",
)
async def auth_start(
    request: Request,
    return_to: str | None = Query(None, description="Relative frontend path to return to."),
) -> Response:
    """Redirect to OpenAI (OIDC + PKCE). Failures redirect to the frontend with ?auth_error=."""
    return await auth.start(request, return_to)


@router.get(
    "/auth/chatgpt/callback",
    response_class=RedirectResponse,
    status_code=302,
    operation_id="authCallback",
)
async def auth_callback(request: Request, db: DB) -> Response:
    """OAuth callback: sets the session cookie and redirects back (?auth_error=denied|failed)."""
    return await auth.callback(request, db)


@router.get(
    "/auth/callback",
    response_class=RedirectResponse,
    status_code=302,
    operation_id="authLoopbackCallback",
)
async def auth_loopback_callback(request: Request, db: DB) -> Response:
    """Same handler on the loopback redirect path the local OAuth flow requires."""
    return await auth.callback(request, db)


@router.get(
    "/auth/google/start",
    response_class=RedirectResponse,
    status_code=302,
    operation_id="authGoogleStart",
    responses={404: {"description": "Google sign-in is not enabled on this server."}},
)
async def auth_google_start(
    return_to: str | None = Query(None, description="Relative frontend path to return to."),
) -> Response:
    """Redirect to Google (OIDC + PKCE). Only when `sign_in_methods` in /auth/session lists
    google; otherwise 404."""
    return await google_auth.start(return_to)


@router.get(
    "/auth/google/callback",
    response_class=RedirectResponse,
    status_code=302,
    operation_id="authGoogleCallback",
    responses={404: {"description": "Google sign-in is not enabled on this server."}},
)
async def auth_google_callback(request: Request, db: DB) -> Response:
    """Google callback: sets the session cookie and redirects back (?auth_error=denied|failed)."""
    return await google_auth.callback(request, db)


@router.post("/auth/logout", status_code=204, operation_id="logout")
async def logout(db: DB, user: OptionalUser, response: Response) -> None:
    """Revoke the stored OpenAI tokens (best effort), delete them and clear the session."""
    await auth.logout(db, user, response)
