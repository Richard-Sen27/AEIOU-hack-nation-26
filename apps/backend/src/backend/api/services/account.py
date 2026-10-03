"""Account: session info, settings, consents, patient profile, data export, deletion."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.config import get_settings
from backend.schemas.account import (
    Consent,
    ConsentGrant,
    CurrentUser,
    DataExport,
    SessionInfo,
    SessionUser,
    SettingsUpdate,
)
from backend.schemas.enums import ConsentType, ErrorCode, Role
from backend.schemas.profile import PatientProfile

_SESSION_USER_SQL = text(
    """
    SELECT u.id, u.name, u.email, p.role, p.role_verified, p.language, p.expert_mode,
           p.age_confirmed_at IS NOT NULL AS age_confirmed,
           COALESCE(
             (SELECT array_agg(DISTINCT c.consent_type ORDER BY c.consent_type) FROM consents c
               WHERE c.user_id = u.id AND c.revoked_at IS NULL),
             '{}'
           ) AS consents
      FROM users u JOIN profiles p ON p.user_id = u.id
     WHERE u.id = :uid
    """
)


async def current_data_version(db: AsyncSession) -> str | None:
    from backend.api.services.graph import get_graph

    version = get_graph().data_version
    if version:
        return version
    return await db.scalar(
        text("SELECT data_version FROM ingestion_runs ORDER BY created_at DESC LIMIT 1")
    )


async def session_user(db: AsyncSession, user_id: UUID) -> SessionUser:
    row = (await db.execute(_SESSION_USER_SQL, {"uid": user_id})).mappings().first()
    if row is None:
        raise ApiError(401, ErrorCode.sign_in_required)
    return SessionUser(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        role=Role(row["role"]) if row["role"] else None,
        role_verified=row["role_verified"],
        language=row["language"] or "en",
        expert_mode=row["expert_mode"],
        age_confirmed=row["age_confirmed"],
        consents=[ConsentType(c) for c in row["consents"]],
    )


async def get_session_info(db: AsyncSession, user: CurrentUser | None, gpc: bool) -> SessionInfo:
    """Who is signed in (or null), GPC signal, demo mode and data version."""
    return SessionInfo(
        user=await session_user(db, user.id) if user else None,
        gpc=gpc,
        demo_mode=get_settings().demo_mode,
        data_version=await current_data_version(db),
    )


async def update_settings(db: AsyncSession, user: CurrentUser, body: SettingsUpdate) -> SessionUser:
    """Update role, language, expert mode or the 16+ confirmation; returns the session user."""
    sets: list[str] = []
    params: dict[str, object] = {"uid": user.id}
    if body.role is not None:
        sets.append("role = :role")
        params["role"] = body.role.value
        if body.role != user.role:
            sets.append("role_verified = false")
            if body.expert_mode is None:  # expert mode is the default for researchers
                sets.append("expert_mode = :expert_default")
                params["expert_default"] = body.role == Role.researcher
    if body.language is not None:
        sets.append("language = :language")
        params["language"] = body.language
    if body.expert_mode is not None:
        sets.append("expert_mode = :expert")
        params["expert"] = body.expert_mode
    if body.age_confirmed_16:
        sets.append("age_confirmed_at = COALESCE(age_confirmed_at, now())")
    if sets:
        sets.append("updated_at = now()")
        await db.execute(
            text(f"UPDATE profiles SET {', '.join(sets)} WHERE user_id = :uid"), params
        )
    return await session_user(db, user.id)


async def list_consents(db: AsyncSession, user: CurrentUser) -> list[Consent]:
    """All of the user's consents, active and revoked."""
    raise NotImplementedError


async def grant_consent(db: AsyncSession, user: CurrentUser, body: ConsentGrant) -> Consent:
    """Grant a consent (idempotent while one is active); stores version and timestamp."""
    raise NotImplementedError


async def revoke_consent(db: AsyncSession, user: CurrentUser, consent_type: ConsentType) -> None:
    """Revoke and delete the data held under that consent (Art. 7(3))."""
    raise NotImplementedError


async def get_profile(db: AsyncSession, user: CurrentUser) -> PatientProfile:
    """The user's PatientProfile (empty profile if none yet)."""
    raise NotImplementedError


async def put_profile(
    db: AsyncSession, user: CurrentUser, profile: PatientProfile
) -> PatientProfile:
    """Replace the PatientProfile (user edits; confirmed items only)."""
    raise NotImplementedError


async def export_data(db: AsyncSession, user: CurrentUser) -> DataExport:
    """All user data as JSON (tokens excluded)."""
    raise NotImplementedError


async def delete_account(db: AsyncSession, user: CurrentUser) -> None:
    """Delete the user row; ON DELETE CASCADE removes everything else."""
    raise NotImplementedError
