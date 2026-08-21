from fastapi import APIRouter

from core.responses import success_response
from shared.contracts.api_contract import ApiResponse
from shared.contracts.health_contract import HealthRead

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[HealthRead])
async def health() -> ApiResponse[HealthRead]:
    return success_response("Service is healthy.", HealthRead(status="ok"))
