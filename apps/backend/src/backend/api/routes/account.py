from fastapi import APIRouter, Response

from backend.api.deps import DB, User
from backend.api.errors import responses
from backend.api.security import clear_session
from backend.api.services import account
from backend.schemas.account import Consent, ConsentGrant, DataExport, SessionUser, SettingsUpdate
from backend.schemas.enums import ConsentType
from backend.schemas.profile import PatientProfile

router = APIRouter(tags=["account"])


@router.patch(
    "/me/settings",
    response_model=SessionUser,
    responses=responses(401, 422),
    operation_id="updateSettings",
)
async def update_settings(body: SettingsUpdate, db: DB, user: User) -> SessionUser:
    """Role, language, expert mode, 16+ confirmation. First sign-in role choice uses this."""
    return await account.update_settings(db, user, body)


@router.get(
    "/me/export",
    response_model=DataExport,
    responses=responses(401, 501),
    operation_id="exportMyData",
)
async def export_my_data(db: DB, user: User) -> DataExport:
    """All user data as JSON."""
    return await account.export_data(db, user)


@router.delete("/me", status_code=204, responses=responses(401, 501), operation_id="deleteMe")
async def delete_me(db: DB, user: User, response: Response) -> None:
    """Delete the account and everything in it; clears the session."""
    await account.delete_account(db, user)
    clear_session(response)


@router.get(
    "/profile",
    response_model=PatientProfile,
    responses=responses(401, 501),
    operation_id="getProfile",
)
async def get_profile(db: DB, user: User) -> PatientProfile:
    """The user's PatientProfile."""
    return await account.get_profile(db, user)


@router.put(
    "/profile",
    response_model=PatientProfile,
    responses=responses(401, 422, 501),
    operation_id="putProfile",
)
async def put_profile(body: PatientProfile, db: DB, user: User) -> PatientProfile:
    """Replace the PatientProfile."""
    return await account.put_profile(db, user, body)


@router.get(
    "/consents",
    response_model=list[Consent],
    responses=responses(401, 501),
    operation_id="listConsents",
)
async def list_consents(db: DB, user: User) -> list[Consent]:
    """The user's consents."""
    return await account.list_consents(db, user)


@router.post(
    "/consents",
    response_model=Consent,
    status_code=201,
    responses=responses(401, 422, 501),
    operation_id="grantConsent",
)
async def grant_consent(body: ConsentGrant, db: DB, user: User) -> Consent:
    """Grant a consent."""
    return await account.grant_consent(db, user, body)


@router.delete(
    "/consents/{consent_type}",
    status_code=204,
    responses=responses(401, 404, 501),
    operation_id="revokeConsent",
)
async def revoke_consent(consent_type: ConsentType, db: DB, user: User) -> None:
    """Revoke a consent and delete the data held under it."""
    await account.revoke_consent(db, user, consent_type)
