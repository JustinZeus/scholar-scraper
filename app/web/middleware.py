from __future__ import annotations

from secrets import token_urlsafe
import time
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_context import set_request_id

REQUEST_ID_HEADER = "X-Request-ID"

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        log_requests: bool = True,
        skip_paths: tuple[str, ...] = (),
    ) -> None:
        super().__init__(app)
        self._log_requests = log_requests
        self._skip_paths = tuple(path for path in skip_paths if path)

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or token_urlsafe(12)
        request.state.request_id = request_id
        set_request_id(request_id)

        start = time.perf_counter()
        should_log = self._log_requests and not self._is_skipped_path(request.url.path)
        if should_log:
            logger.info(
                "request.started",
                extra={
                    "event": "request.started",
                    "method": request.method,
                    "path": request.url.path,
                },
            )

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "request.failed",
                extra={
                    "event": "request.failed",
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                },
            )
            raise
        else:
            duration_ms = int((time.perf_counter() - start) * 1000)
            response.headers[REQUEST_ID_HEADER] = request_id
            if should_log:
                logger.info(
                    "request.completed",
                    extra={
                        "event": "request.completed",
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                    },
                )
            return response
        finally:
            set_request_id(None)

    def _is_skipped_path(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self._skip_paths)


def parse_skip_paths(raw_value: str) -> tuple[str, ...]:
    parts = [part.strip() for part in raw_value.split(",")]
    return tuple(part for part in parts if part)
