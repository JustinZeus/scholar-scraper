from __future__ import annotations

from secrets import token_urlsafe
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_context import set_request_id

REQUEST_ID_HEADER = "X-Request-ID"
DEFAULT_PERMISSIONS_POLICY = (
    "accelerometer=(), autoplay=(), camera=(), display-capture=(), "
    "geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()"
)
DEFAULT_CSP_POLICY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "img-src 'self' data: https:; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'"
)
DEFAULT_CSP_DOCS_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data: https:; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; "
    "connect-src 'self' https:; "
    "object-src 'none'; "
    "frame-ancestors 'none'"
)

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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        enabled: bool = True,
        x_content_type_options: str = "nosniff",
        x_frame_options: str = "DENY",
        referrer_policy: str = "strict-origin-when-cross-origin",
        permissions_policy: str = DEFAULT_PERMISSIONS_POLICY,
        cross_origin_opener_policy: str = "same-origin",
        cross_origin_resource_policy: str = "same-origin",
        content_security_policy_enabled: bool = True,
        content_security_policy: str = DEFAULT_CSP_POLICY,
        content_security_policy_docs: str = DEFAULT_CSP_DOCS_POLICY,
        content_security_policy_report_only: bool = False,
        strict_transport_security_enabled: bool = False,
        strict_transport_security_max_age: int = 31_536_000,
        strict_transport_security_include_subdomains: bool = True,
        strict_transport_security_preload: bool = False,
    ) -> None:
        super().__init__(app)
        self._enabled = enabled
        self._x_content_type_options = x_content_type_options.strip()
        self._x_frame_options = x_frame_options.strip()
        self._referrer_policy = referrer_policy.strip()
        self._permissions_policy = permissions_policy.strip()
        self._cross_origin_opener_policy = cross_origin_opener_policy.strip()
        self._cross_origin_resource_policy = cross_origin_resource_policy.strip()
        self._csp_enabled = content_security_policy_enabled
        self._csp_policy = content_security_policy.strip()
        self._csp_docs_policy = content_security_policy_docs.strip()
        self._csp_report_only = content_security_policy_report_only
        self._hsts_enabled = strict_transport_security_enabled
        self._hsts_max_age = max(0, strict_transport_security_max_age)
        self._hsts_include_subdomains = strict_transport_security_include_subdomains
        self._hsts_preload = strict_transport_security_preload

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if not self._enabled:
            return response

        if self._x_content_type_options:
            response.headers.setdefault("X-Content-Type-Options", self._x_content_type_options)
        if self._x_frame_options:
            response.headers.setdefault("X-Frame-Options", self._x_frame_options)
        if self._referrer_policy:
            response.headers.setdefault("Referrer-Policy", self._referrer_policy)
        if self._permissions_policy:
            response.headers.setdefault("Permissions-Policy", self._permissions_policy)
        if self._cross_origin_opener_policy:
            response.headers.setdefault(
                "Cross-Origin-Opener-Policy",
                self._cross_origin_opener_policy,
            )
        if self._cross_origin_resource_policy:
            response.headers.setdefault(
                "Cross-Origin-Resource-Policy",
                self._cross_origin_resource_policy,
            )

        csp_policy = self._csp_policy_for_path(request.url.path)
        if self._csp_enabled and csp_policy:
            csp_header = (
                "Content-Security-Policy-Report-Only"
                if self._csp_report_only
                else "Content-Security-Policy"
            )
            response.headers.setdefault(csp_header, csp_policy)

        hsts = self._strict_transport_security_value()
        if hsts:
            response.headers.setdefault("Strict-Transport-Security", hsts)

        return response

    def _csp_policy_for_path(self, path: str) -> str:
        if path.startswith("/docs") or path.startswith("/redoc"):
            return self._csp_docs_policy or self._csp_policy
        return self._csp_policy

    def _strict_transport_security_value(self) -> str:
        if not self._hsts_enabled:
            return ""

        directives = [f"max-age={self._hsts_max_age}"]
        if self._hsts_include_subdomains:
            directives.append("includeSubDomains")
        if self._hsts_preload:
            directives.append("preload")
        return "; ".join(directives)


def parse_skip_paths(raw_value: str) -> tuple[str, ...]:
    parts = [part.strip() for part in raw_value.split(",")]
    return tuple(part for part in parts if part)
