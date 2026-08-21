from core.errors import AppError
from shared.contracts.api_contract import ApiError, ApiResponse


def success_response[T](message: str, data: T | None = None) -> ApiResponse[T]:
    return ApiResponse(
        success=True,
        message=message,
        data=data,
        error=None,
    )


def error_response(exc: AppError) -> ApiResponse[None]:
    return ApiResponse(
        success=False,
        message="Request failed.",
        data=None,
        error=ApiError(
            code=exc.code,
            detail=exc.detail,
            fields=exc.fields,
        ),
    )
