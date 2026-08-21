from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from core.errors import AppError, ErrorCode
from core.responses import error_response


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return _json_error_response(
        AppError(
            "Request validation failed.",
            code=ErrorCode.VALIDATION_ERROR,
            fields=_validation_fields(exc.errors()),
        ),
        status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


async def http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    return _json_error_response(
        AppError(
            str(exc.detail),
            code=ErrorCode.HTTP_ERROR,
        ),
        exc.status_code,
    )


def _json_error_response(exc: AppError, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_response(exc).model_dump(mode="json"),
    )


def _validation_fields(errors: Sequence[dict[str, Any]]) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for error in errors:
        field = ".".join(str(part) for part in error.get("loc", []))
        fields.setdefault(field, []).append(str(error.get("msg", "Invalid value.")))

    return fields
