from __future__ import annotations

import logging
from secrets import compare_digest, token_urlsafe
from urllib.parse import parse_qs

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.types import Message


CSRF_SESSION_KEY = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
logger = logging.getLogger(__name__)


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if token is None:
        token = token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return str(token)


class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, exempt_paths: set[str] | None = None) -> None:
        super().__init__(app)
        self._exempt_paths = exempt_paths or set()

    async def dispatch(self, request: Request, call_next) -> Response:
        if self._should_skip(request):
            return await call_next(request)

        session_token = request.session.get(CSRF_SESSION_KEY)
        if not session_token:
            logger.warning(
                "csrf.missing_session_token",
                extra={
                    "event": "csrf.missing_session_token",
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            return self._csrf_error_response(
                request,
                code="csrf_missing",
                message="CSRF token missing.",
            )

        request_token = request.headers.get(CSRF_HEADER_NAME)
        if request_token is None and self._is_form_payload(request):
            body = await request.body()
            request_token = self._token_from_form_body(request, body)
            request._receive = self._build_receive(body)  # type: ignore[attr-defined]

        if not request_token or not compare_digest(str(session_token), str(request_token)):
            logger.warning(
                "csrf.invalid_token",
                extra={
                    "event": "csrf.invalid_token",
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            return self._csrf_error_response(
                request,
                code="csrf_invalid",
                message="CSRF token invalid.",
            )

        return await call_next(request)

    def _should_skip(self, request: Request) -> bool:
        if request.method in SAFE_METHODS:
            return True
        path = request.url.path
        return path in self._exempt_paths

    def _is_form_payload(self, request: Request) -> bool:
        content_type = request.headers.get("content-type", "")
        return content_type.startswith("application/x-www-form-urlencoded") or (
            content_type.startswith("multipart/form-data")
        )

    def _token_from_form_body(self, request: Request, body: bytes) -> str | None:
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("application/x-www-form-urlencoded"):
            return None
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        values = parsed.get(CSRF_FORM_FIELD)
        if not values:
            return None
        return values[0]

    def _build_receive(self, body: bytes):
        consumed = False

        async def receive() -> Message:
            nonlocal consumed
            if consumed:
                return {"type": "http.request", "body": b"", "more_body": False}
            consumed = True
            return {"type": "http.request", "body": body, "more_body": False}

        return receive

    def _csrf_error_response(
        self,
        request: Request,
        *,
        code: str,
        message: str,
    ) -> Response:
        if request.url.path.startswith("/api/"):
            request_state = getattr(request, "state", None)
            request_id = getattr(request_state, "request_id", None) if request_state else None
            return JSONResponse(
                {
                    "error": {
                        "code": code,
                        "message": message,
                        "details": None,
                    },
                    "meta": {
                        "request_id": request_id,
                    },
                },
                status_code=403,
            )
        return PlainTextResponse(message, status_code=403)
