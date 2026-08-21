from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.errors import AppError, ConflictError, ErrorCode
from core.responses import error_response
from db.database import database
from shared.constants.http_constant import TRANSACTION_METHODS, TRANSACTION_SKIP_PATHS


class AppMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True

            await send(message)

        try:
            if self._should_wrap_transaction(request):
                await self._call_with_transaction(request, receive, send_wrapper)
            else:
                await self.app(scope, receive, send_wrapper)
        except IntegrityError:
            if response_started:
                raise
            response = self._error_response(
                ConflictError(
                    "Database constraint violated.",
                    code=ErrorCode.DATABASE_CONSTRAINT_VIOLATION,
                ),
            )
            await response(scope, receive, send)
        except AppError as exc:
            if response_started:
                raise
            response = self._error_response(exc)
            await response(scope, receive, send)
        except Exception as exc:
            if response_started:
                raise
            response = self._error_response(AppError(str(exc)))
            await response(scope, receive, send)

    async def _call_with_transaction(
        self,
        request: Request,
        receive: Receive,
        send: Send,
    ) -> None:
        response_status_code = 500
        scope = request.scope

        async def send_wrapper(message: Message) -> None:
            nonlocal response_status_code
            if message["type"] == "http.response.start":
                response_status_code = message["status"]

            await send(message)

        with database.transaction() as session:
            request.state.db = session
            try:
                await self.app(scope, receive, send_wrapper)
            except Exception:
                session.rollback()
                raise

            if response_status_code >= 400:
                session.rollback()
            else:
                session.commit()

    def _should_wrap_transaction(self, request: Request) -> bool:
        return (
            request.method in TRANSACTION_METHODS
            and request.url.path not in TRANSACTION_SKIP_PATHS
        )

    def _error_response(self, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response(exc).model_dump(mode="json"),
        )
