from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

PLAN_USAGE_SCOPE = "chatgpt.tokens.use.direct"
REFRESH_SKEW = timedelta(minutes=5)


def _now() -> datetime:
    return datetime.now(UTC)


def parse_instant(value: Any) -> datetime | None:
    """Accept unix seconds (int/float/str) or ISO-8601; return an aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), UTC)
    if isinstance(value, str):
        try:
            return datetime.fromtimestamp(float(value), UTC)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


class TokenSet(BaseModel):
    """OAuth tokens for one registration. Never log or serialize this outside encrypted storage."""

    access_token: str = Field(repr=False)
    refresh_token: str | None = Field(default=None, repr=False)
    id_token: str | None = Field(default=None, repr=False)
    token_type: str = "Bearer"
    expires_at: datetime
    scopes: list[str] = Field(default_factory=list)
    earliest_refresh_at: datetime | None = None
    issued_at: datetime | None = None
    client_id: str

    @classmethod
    def from_token_response(
        cls, data: dict[str, Any], *, client_id: str, previous: "TokenSet | None" = None
    ) -> "TokenSet":
        now = _now()
        expires_in = data.get("expires_in")
        try:
            expires_at = now + timedelta(seconds=int(expires_in)) if expires_in else None
        except (TypeError, ValueError):
            expires_at = None
        scope = data.get("scope")
        if isinstance(scope, list):
            scopes = [str(s) for s in scope]
        elif isinstance(scope, str):
            scopes = scope.split()
        else:
            scopes = list(previous.scopes) if previous else []
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token")
            or (previous.refresh_token if previous else None),
            id_token=data.get("id_token") or (previous.id_token if previous else None),
            token_type=data.get("token_type") or "Bearer",
            expires_at=expires_at or now + timedelta(hours=1),
            scopes=scopes,
            earliest_refresh_at=parse_instant(data.get("earliest_refresh_at")),
            issued_at=now,
            client_id=client_id,
        )

    @property
    def has_plan_usage(self) -> bool:
        return PLAN_USAGE_SCOPE in self.scopes

    def is_expired(self, *, skew: timedelta = timedelta(0)) -> bool:
        return _now() >= self.expires_at - skew

    def needs_refresh(self, *, skew: timedelta = REFRESH_SKEW) -> bool:
        """Refresh `skew` before expiry (at most half the lifetime, so short-lived tokens are
        not refreshed on every use)."""
        if not self.refresh_token:
            return False
        if self.issued_at is not None:
            skew = max(timedelta(0), min(skew, (self.expires_at - self.issued_at) / 2))
        if self.earliest_refresh_at and _now() < self.earliest_refresh_at:
            return self.is_expired()
        return self.is_expired(skew=skew)

    def __repr__(self) -> str:
        return f"TokenSet(client_id={self.client_id!r}, expires_at={self.expires_at.isoformat()})"

    __str__ = __repr__
