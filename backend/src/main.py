from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from api.router import api_router
from core.config import settings
from core.exception_handlers import (
    http_exception_handler,
    validation_exception_handler,
)
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
