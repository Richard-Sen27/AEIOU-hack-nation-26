from fastapi import APIRouter

from backend.schemas.common import ApiModel

router = APIRouter(tags=["health"])


class Health(ApiModel):
    status: str = "ok"


@router.get("/health", response_model=Health, operation_id="health")
async def health() -> Health:
    return Health()
