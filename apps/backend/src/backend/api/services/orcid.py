"""ORCID sign-in that confirms a doctor's or researcher's ORCID iD (OAuth 2, scope /authenticate).

Real ORCID: ORCID_CLIENT_ID, ORCID_CLIENT_SECRET, ORCID_BASE_URL (sandbox or production) and the
registered ORCID_REDIRECT_URI. The token response carries the ORCID iD and the public name; the
access token is discarded at once and never stored.

Local demo: ORCID_MOCK=true uses the simulated sign-in in backend.devtools.mock_orcid. Settings
refuse the mock unless API and frontend are loopback, and every call here checks again.
Verifications through the mock are stored as `orcid_simulated` and labelled as simulated.

The `state` parameter is a short-lived token signed with SESSION_SECRET and bound to the user who
started the flow; each one is accepted once per process.
"""

import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
import jwt

from backend.config import get_settings
from backend.schemas.account import _clean_orcid

log = logging.getLogger(__name__)

STATE_TTL_S = 600
STATE_AUDIENCE = "amber-orcid"
SCOPE = "/authenticate"
MOCK_PREFIX = "/_mock/orcid"
CALLBACK_PATH = "/me/professional/orcid/callback"
_TOKEN_TIMEOUT_S = 10.0
_MAX_NAME = 200

_used_nonces: dict[str, float] = {}


class OrcidError(Exception):
    """The exchange failed; never carries tokens or response bodies."""


@dataclass(frozen=True)
class OrcidIdentity:
    orcid_id: str
    name: str | None
    simulated: bool


def mock_enabled() -> bool:
    s = get_settings()
    return bool(s.orcid_mock and s.is_local)


def mode() -> str | None:
    """'mock', 'real', or None when ORCID sign-in is not configured."""
    s = get_settings()
    if s.orcid_mock:
        return "mock" if mock_enabled() else None
    if s.orcid_client_id and s.orcid_client_secret:
        return "real"
    return None


def redirect_uri() -> str:
    s = get_settings()
    return s.orcid_redirect_uri or s.api_url.rstrip("/") + CALLBACK_PATH


def make_state(user_id: UUID, return_to: str, simulated: bool) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "nonce": secrets.token_urlsafe(16),
        "rt": return_to,
        "sim": simulated,
        "iat": now,
        "exp": now + STATE_TTL_S,
        "aud": STATE_AUDIENCE,
    }
    return jwt.encode(payload, get_settings().session_secret, algorithm="HS256")


def read_state(state: str | None, user_id: UUID) -> dict[str, Any] | None:
    """The state's claims if it is valid, unexpired, unused and was issued to this user.

    Marks it used, so a replayed callback fails."""
    if not state or len(state) > 2048:
        return None
    try:
        claims = jwt.decode(
            state,
            get_settings().session_secret,
            algorithms=["HS256"],
            audience=STATE_AUDIENCE,
            options={"require": ["sub", "nonce", "exp", "aud"]},
        )
    except jwt.PyJWTError:
        return None
    if claims.get("sub") != str(user_id):
        return None
    now = time.time()
    for nonce, exp in list(_used_nonces.items()):
        if exp < now:
            del _used_nonces[nonce]
    nonce = str(claims["nonce"])
    if nonce in _used_nonces:
        return None
    _used_nonces[nonce] = float(claims["exp"])
    return claims


def authorize_url(state: str, orcid_hint: str | None = None) -> str:
    s = get_settings()
    params = {
        "client_id": s.orcid_client_id or "amber-mock",
        "response_type": "code",
        "scope": SCOPE,
        "redirect_uri": redirect_uri(),
        "state": state,
    }
    if mode() == "mock":
        if orcid_hint:
            params["orcid"] = orcid_hint
        return f"{s.api_url.rstrip('/')}{MOCK_PREFIX}/oauth/authorize?{urlencode(params)}"
    return f"{s.orcid_base_url.rstrip('/')}/oauth/authorize?{urlencode(params)}"


def _clean_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    if not value or any(ord(c) < 32 for c in value):
        return None
    return value[:_MAX_NAME]


def _identity(orcid: Any, name: Any, simulated: bool) -> OrcidIdentity:
    try:
        orcid_id = _clean_orcid(orcid) if isinstance(orcid, str) else None
    except ValueError:
        orcid_id = None
    if orcid_id is None:
        raise OrcidError("invalid ORCID iD in the response")
    return OrcidIdentity(orcid_id=orcid_id, name=_clean_name(name), simulated=simulated)


async def exchange(code: str | None, simulated: bool) -> OrcidIdentity:
    """Trade the authorization code for the ORCID iD and public name."""
    if not code or len(code) > 512:
        raise OrcidError("missing code")
    current = mode()
    if simulated:
        if current != "mock":
            raise OrcidError("the simulated sign-in is off")
        from backend.devtools.mock_orcid.state import redeem_code

        grant = redeem_code(code, redirect_uri())
        if grant is None:
            raise OrcidError("unknown or used code")
        return _identity(grant.orcid_id, grant.name, simulated=True)
    if current != "real":
        raise OrcidError("ORCID sign-in is not configured")
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT_S) as client:
            resp = await client.post(
                f"{s.orcid_base_url.rstrip('/')}/oauth/token",
                data={
                    "client_id": s.orcid_client_id,
                    "client_secret": s.orcid_client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri(),
                },
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        log.warning("ORCID token request failed: %s", type(exc).__name__)
        raise OrcidError("token request failed") from None
    if resp.status_code != 200:
        log.warning("ORCID token request returned %s", resp.status_code)
        raise OrcidError("token request rejected")
    try:
        body = resp.json()
    except ValueError:
        raise OrcidError("token response is not JSON") from None
    if not isinstance(body, dict):
        raise OrcidError("unexpected token response")
    return _identity(body.get("orcid"), body.get("name"), simulated=False)
