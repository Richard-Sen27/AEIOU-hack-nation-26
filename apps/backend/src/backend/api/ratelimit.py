from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from backend.api.security import COOKIE_NAME, verify_session_token

UPLOAD_LIMIT = "10/hour"
GAP_SEARCH_LIMIT = "20/hour"


def user_or_ip(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    claims = verify_session_token(token) if token else None
    return f"user:{claims.user_id}" if claims else f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=user_or_ip)
