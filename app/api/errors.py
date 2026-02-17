from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import (
    http_exception_handler as fastapi_http_exception_handler,
)
from fastapi.exception_handlers import (
    request_validation_exception_handler as fastapi_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError

from app.api.responses import error_response


def _is_api_path(path: str) -> bool:
    return path.startswith("/api/")


def _status_code_to_error_code(status_code: int) -> str:
    mapping = {
        400: "bad_request",
        401: "auth_required",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        429: "rate_limited",
        500: "internal_error",
    }
    return mapping.get(status_code, "error")


class ApiException(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def register_api_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiException)
    async def _handle_api_exception(request: Request, exc: ApiException):
        return error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(HTTPException)
    async def _handle_http_exception(request: Request, exc: HTTPException):
        if not _is_api_path(request.url.path):
            return await fastapi_http_exception_handler(request, exc)
        return error_response(
            request,
            status_code=exc.status_code,
            code=_status_code_to_error_code(exc.status_code),
            message=str(exc.detail) if exc.detail is not None else "Request failed.",
            details=exc.detail if isinstance(exc.detail, (dict, list)) else None,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_exception(request: Request, exc: RequestValidationError):
        if not _is_api_path(request.url.path):
            return await fastapi_validation_exception_handler(request, exc)
        return error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed.",
            details=exc.errors(),
        )

