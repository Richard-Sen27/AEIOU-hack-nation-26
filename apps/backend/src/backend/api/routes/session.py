from fastapi import APIRouter, Request

from backend.api.deps import DB, OptionalUser, gpc_signal
from backend.api.services import account
from backend.schemas.account import SessionInfo

router = APIRouter(tags=["auth"])


@router.get("/auth/session", response_model=SessionInfo, operation_id="getSession")
async def get_session(request: Request, db: DB, user: OptionalUser) -> SessionInfo:
    """The signed-in user (or null for guests), GPC signal, demo mode and data version."""
    return await account.get_session_info(db, user, gpc_signal(request))
