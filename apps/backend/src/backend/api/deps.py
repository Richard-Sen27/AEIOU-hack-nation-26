from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.api.security import COOKIE_NAME, clear_session, issue_session, verify_session_token
from backend.db.session import get_db, set_user
from backend.schemas.account import CurrentUser
from backend.schemas.common import LANGUAGE_PATTERN, Lens
from backend.schemas.enums import ConsentType, ErrorCode, Role

__all__ = [
    "DB",
    "OptionalUser",
    "User",
    "LensDep",
    "get_db",
    "get_optional_user",
    "require_user",
    "require_signed_in",
    "SignedInUser",
    "require_consent",
    "HealthDataConsentUser",
    "ContributeConsentUser",
    "get_lens",
    "build_lens",
    "gpc_signal",
]

# scope="function": the request transaction commits before the response is sent, and SSE
# handlers do not keep it open while streaming (they use user_transaction instead).
_PROFILE_SQL = text(
    "SELECT role, role_verified, language, expert_mode, age_confirmed_at IS NOT NULL AS age_ok,"
    " gpc_opt_out FROM profiles WHERE user_id = :uid"
)


def gpc_signal(request: Request) -> bool:
    return request.headers.get("sec-gpc", "").strip() == "1"


async def get_optional_user(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db, scope="function")],
) -> CurrentUser | None:
    """Verify the session cookie; scope the request transaction to the user (or guest)."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    claims = verify_session_token(token)
    if claims is None:
        clear_session(response)
        return None

    await set_user(db, claims.user_id)
    row = (await db.execute(_PROFILE_SQL, {"uid": claims.user_id})).mappings().first()
    if row is None:  # account deleted
        await set_user(db, None)
        clear_session(response)
        return None

    gpc = gpc_signal(request)
    if gpc and not row["gpc_opt_out"]:
        await db.execute(
            text("UPDATE profiles SET gpc_opt_out = true, updated_at = now() WHERE user_id = :uid"),
            {"uid": claims.user_id},
        )
    if claims.needs_refresh():
        issue_session(response, claims.user_id)

    return CurrentUser(
        id=claims.user_id,
        role=Role(row["role"]) if row["role"] else None,
        role_verified=row["role_verified"],
        language=row["language"] or "en",
        expert_mode=row["expert_mode"],
        age_confirmed=row["age_ok"],
        gpc_opt_out=row["gpc_opt_out"] or gpc,
    )


async def require_signed_in(
    user: Annotated[CurrentUser | None, Depends(get_optional_user)],
) -> CurrentUser:
    """Signed in, 16+ confirmation not needed: only onboarding and account/data-rights routes."""
    if user is None:
        raise ApiError(401, ErrorCode.sign_in_required)
    return user


async def require_user(
    user: Annotated[CurrentUser, Depends(require_signed_in)],
) -> CurrentUser:
    """Signed in and confirmed 16+ (GDPR Art. 8); every feature route depends on this."""
    if not user.age_confirmed:
        raise ApiError(
            403,
            ErrorCode.age_confirmation_required,
            "Confirm that you are 16 or older to use this feature.",
        )
    return user


def require_consent(consent_type: ConsentType) -> Callable[..., Awaitable[CurrentUser]]:
    """Dependency factory: 403 consent_required without an active consent of this type."""

    async def _require(
        user: Annotated[CurrentUser, Depends(require_user)],
        db: Annotated[AsyncSession, Depends(get_db, scope="function")],
    ) -> CurrentUser:
        found = await db.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM consents WHERE consent_type = :t"
                " AND revoked_at IS NULL)"
            ),
            {"t": consent_type.value},
        )
        if not found:
            raise ApiError(403, ErrorCode.consent_required)
        return user

    _require.__name__ = f"require_consent_{consent_type.value}"
    return _require


async def get_lens(
    user: Annotated[CurrentUser | None, Depends(get_optional_user)],
    role: Annotated[Role | None, Query(description="Presentation role override.")] = None,
    language: Annotated[
        str | None, Query(pattern=LANGUAGE_PATTERN, description="Output language override.")
    ] = None,
) -> Lens:
    """Role and language for presentation: query params, then profile, then guest/en."""
    return build_lens(user, role, language)


def build_lens(
    user: CurrentUser | None,
    role: Role | None = None,
    language: str | None = None,
    expert_mode: bool | None = None,
) -> Lens:
    return Lens(
        role=role or (user.role if user and user.role else Role.guest),
        language=language or (user.language if user else "en"),
        expert_mode=bool(user and user.expert_mode) if expert_mode is None else expert_mode,
    )


DB = Annotated[AsyncSession, Depends(get_db, scope="function")]
OptionalUser = Annotated[CurrentUser | None, Depends(get_optional_user)]
User = Annotated[CurrentUser, Depends(require_user)]
SignedInUser = Annotated[CurrentUser, Depends(require_signed_in)]
LensDep = Annotated[Lens, Depends(get_lens)]
HealthDataConsentUser = Annotated[CurrentUser, Depends(require_consent(ConsentType.health_data))]
ContributeConsentUser = Annotated[CurrentUser, Depends(require_consent(ConsentType.contribute))]
