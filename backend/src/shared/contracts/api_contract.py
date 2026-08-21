from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiError(BaseModel):
    code: str
    detail: str
    fields: dict[str, list[str]] | None = None


class ApiResponse(BaseModel, Generic[T]):
    success: bool
    message: str
    data: T | None = None
    error: ApiError | None = None


class PaginatedData(BaseModel, Generic[T]):
    page: int
    limit: int
    total: int
    items: list[T]


class ApiPaginatedResponse(ApiResponse[PaginatedData[T]], Generic[T]):
    pass
