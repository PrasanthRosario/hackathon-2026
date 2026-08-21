import os

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles

from api.router import api_router
from core.config import settings
from core.exception_handlers import (
    http_exception_handler,
    validation_exception_handler,
)
from modules.offset_agent.router import router as offset_agent_router
from shared.middlewares.app_middleware import AppMiddleware
from shared.utils.logging import configure_logging

# Logging configuration
configure_logging(settings.log_level)

# Initializing fast api app instance
app = FastAPI(title=settings.app_name)

# Configure middleware
app.add_middleware(AppMiddleware)

# Configure exception handlers
app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]

# Register all the routers
app.include_router(api_router)
app.include_router(offset_agent_router)  # Includes root level /render and /render/{scene_id}/status

# Mount /renders static directory (prefers /home/ubuntu/renders, falls back to repo renders/ dir)
renders_dir = "/home/ubuntu/renders" if os.path.exists("/home/ubuntu/renders") else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "renders"))
os.makedirs(renders_dir, exist_ok=True)
app.mount("/renders", StaticFiles(directory=renders_dir), name="renders")
