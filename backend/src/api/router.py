from fastapi import APIRouter

from api.health import router as health_router

api_router = APIRouter()

# Health routes
api_router.include_router(health_router)
