"""In-memory authorization codes of the simulated ORCID sign-in (one API process, dev only)."""

import secrets
import time
from dataclasses import dataclass

CODE_TTL_S = 300
_MAX_CODES = 1000


@dataclass(frozen=True)
class MockGrant:
    orcid_id: str
    name: str | None
    redirect_uri: str
    expires_at: float


_codes: dict[str, MockGrant] = {}


def issue_code(orcid_id: str, name: str | None, redirect_uri: str) -> str:
    """A single-use code for this identity, valid for CODE_TTL_S seconds."""
    now = time.monotonic()
    for code, grant in list(_codes.items()):
        if grant.expires_at < now:
            del _codes[code]
    if len(_codes) >= _MAX_CODES:
        _codes.clear()
    code = secrets.token_urlsafe(24)
    _codes[code] = MockGrant(orcid_id, name, redirect_uri, now + CODE_TTL_S)
    return code


def redeem_code(code: str, redirect_uri: str) -> MockGrant | None:
    """The grant for a code (removed on first use); None if unknown, expired or reused, or if
    the redirect URI differs from the one the code was issued for."""
    grant = _codes.pop(code, None)
    if grant is None or grant.expires_at < time.monotonic() or grant.redirect_uri != redirect_uri:
        return None
    return grant


def reset() -> None:
    _codes.clear()
