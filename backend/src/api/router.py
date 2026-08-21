from fastapi import APIRouter

from api.health import router as health_router
from modules.offset_agent.router import router as offset_agent_router

api_router = APIRouter()

# Health routes
api_router.include_router(health_router)

# Offset Pre-Viz Agent routes under /offset and /api for full compatibility
api_router.include_router(offset_agent_router, prefix="/offset")
api_router.include_router(offset_agent_router, prefix="/api")
