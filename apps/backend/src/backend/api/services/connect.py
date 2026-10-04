"""The `connect` consent ("Studies, surveys and contacts") and the self-declared age group.

`connect` is the third consent type: contact with other people is a different purpose from the
user's own use (`health_data`) and from sharing with the atlas (`contribute`). It covers
messaging today and suggestions and sign-ups later (stage 4).

Withdrawal runs every effect in `_withdrawal_effects()` inside the user's transaction, then
clears the age group. A feature held under this consent adds its effect there with one line.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.schemas.account import CurrentUser
from backend.schemas.enums import ConsentType, ErrorCode
from backend.schemas.messaging import (
    GUARDIAN_TEXT,
    GUARDIAN_TEXT_VERSION,
    REPORT_AUTHORIZATION_TEXT,
    REPORT_AUTHORIZATION_VERSION,
    AgeGroup,
    ConnectStatus,
)

WithdrawalEffect = Callable[[AsyncSession, UUID], Awaitable[None]]


def _withdrawal_effects() -> tuple[WithdrawalEffect, ...]:
    """What withdrawing `connect` deletes or closes, one entry per feature."""
    from backend.api.services import messaging  # messaging imports this module

    return (
        messaging.on_connect_withdrawn,  # deletes the user's messages, closes their threads
        # stage 4 adds: signups.on_connect_withdrawn (suggestions off, sign-ups withdrawn)
    )


async def has_consent(db: AsyncSession, user_id: UUID) -> bool:
    return bool(
        await db.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM consents WHERE user_id = :uid AND consent_type = :t"
                " AND revoked_at IS NULL)"
            ),
            {"uid": user_id, "t": ConsentType.connect.value},
        )
    )


async def _age_row(db: AsyncSession, user_id: UUID):
    return (
        (
            await db.execute(
                text(
                    "SELECT connect_age_group, connect_age_group_at FROM profiles"
                    " WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
        )
        .mappings()
        .first()
    )


async def age_group(db: AsyncSession, user_id: UUID) -> AgeGroup | None:
    row = await _age_row(db, user_id)
    return AgeGroup(row["connect_age_group"]) if row and row["connect_age_group"] else None


async def require_age_group(db: AsyncSession, user_id: UUID) -> AgeGroup:
    group = await age_group(db, user_id)
    if group is None:
        raise ApiError(403, ErrorCode.age_group_required)
    return group


async def get_status(db: AsyncSession, user: CurrentUser) -> ConnectStatus:
    row = await _age_row(db, user.id)
    return ConnectStatus(
        consent_active=await has_consent(db, user.id),
        age_group=AgeGroup(row["connect_age_group"]) if row and row["connect_age_group"] else None,
        age_group_set_at=row["connect_age_group_at"] if row else None,
        guardian_text=GUARDIAN_TEXT,
        guardian_text_version=GUARDIAN_TEXT_VERSION,
        report_authorization_text=REPORT_AUTHORIZATION_TEXT,
        report_authorization_version=REPORT_AUTHORIZATION_VERSION,
    )


async def set_age_group(db: AsyncSession, user: CurrentUser, group: AgeGroup) -> ConnectStatus:
    """State or correct the age group (needs the connect consent; checked by the route)."""
    await db.execute(
        text(
            "UPDATE profiles SET connect_age_group = :g, connect_age_group_at = now(),"
            " updated_at = now() WHERE user_id = :uid"
        ),
        {"uid": user.id, "g": group.value},
    )
    return await get_status(db, user)


async def withdraw(db: AsyncSession, user_id: UUID) -> None:
    """Withdrawal of `connect` (the consent row is already revoked by the caller)."""
    for effect in _withdrawal_effects():
        await effect(db, user_id)
    await db.execute(
        text(
            "UPDATE profiles SET connect_age_group = NULL, connect_age_group_at = NULL,"
            " updated_at = now() WHERE user_id = :uid"
        ),
        {"uid": user_id},
    )
