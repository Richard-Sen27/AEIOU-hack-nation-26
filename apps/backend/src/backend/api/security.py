"""Session cookie: a short-lived HS256 JWT (sub = user id) with sliding refresh."""

import time
from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Response

from backend.config import get_settings

COOKIE_NAME = "amber_session"
ALGORITHM = "HS256"
ISSUER = "amber-api"


@dataclass(frozen=True)
class SessionClaims:
    user_id: UUID
    issued_at: int
    expires_at: int

    def needs_refresh(self, now: float | None = None) -> bool:
        """True when more than half of the token's life is used."""
        now = time.time() if now is None else now
        return now - self.issued_at > (self.expires_at - self.issued_at) / 2


def create_session_token(user_id: UUID | str, now: float | None = None) -> str:
    settings = get_settings()
    issued = int(time.time() if now is None else now)
    payload = {
        "sub": str(user_id),
        "iat": issued,
        "exp": issued + settings.session_ttl_minutes * 60,
        "iss": ISSUER,
    }
    return jwt.encode(payload, settings.session_secret, algorithm=ALGORITHM)


def verify_session_token(token: str) -> SessionClaims | None:
    try:
        payload = jwt.decode(
            token,
            get_settings().session_secret,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["sub", "iat", "exp", "iss"]},
        )
        return SessionClaims(UUID(payload["sub"]), int(payload["iat"]), int(payload["exp"]))
    except (jwt.PyJWTError, ValueError, KeyError):
        return None


def issue_session(response: Response, user_id: UUID | str) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(user_id),
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )
