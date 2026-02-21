from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.errors import register_api_exception_handlers
from app.api.media import router as media_router
from app.api.router import router as api_router
from app.api.runtime_deps import get_ingestion_service, get_scholar_source
from app.db.session import check_database
from app.db.session import close_engine
from app.http.middleware import (
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    parse_skip_paths,
)
from app.logging_config import configure_logging, parse_redact_fields
from app.security.csrf import CSRFMiddleware
from app.services.domains.ingestion.scheduler import SchedulerService
from app.settings import settings

logger = logging.getLogger(__name__)
BUILD_MARKER = "2026-02-19.phase2.direct-pdf-import-export-dashboard-sync"

configure_logging(
    level=settings.log_level,
    log_format=settings.log_format,
    redact_fields=parse_redact_fields(settings.log_redact_fields),
    include_uvicorn_access=settings.log_uvicorn_access,
)

scheduler_service = SchedulerService(
    enabled=settings.scheduler_enabled,
    tick_seconds=settings.scheduler_tick_seconds,
    network_error_retries=settings.ingestion_network_error_retries,
    retry_backoff_seconds=settings.ingestion_retry_backoff_seconds,
    max_pages_per_scholar=settings.ingestion_max_pages_per_scholar,
    page_size=settings.ingestion_page_size,
    continuation_queue_enabled=settings.ingestion_continuation_queue_enabled,
    continuation_base_delay_seconds=settings.ingestion_continuation_base_delay_seconds,
    continuation_max_delay_seconds=settings.ingestion_continuation_max_delay_seconds,
    continuation_max_attempts=settings.ingestion_continuation_max_attempts,
    queue_batch_size=settings.scheduler_queue_batch_size,
)


def _log_startup_build_marker() -> None:
    logger.info(
        "app.startup_build_marker",
        extra={
            "event": "app.startup_build_marker",
            "build_marker": BUILD_MARKER,
            "frontend_enabled": settings.frontend_enabled,
            "scheduler_enabled": settings.scheduler_enabled,
            "log_format": settings.log_format,
        },
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    _log_startup_build_marker()
    await scheduler_service.start()
    yield
    await scheduler_service.stop()
    await close_engine()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
register_api_exception_handlers(app)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    same_site="lax",
    https_only=settings.session_cookie_secure,
)
app.add_middleware(
    RequestLoggingMiddleware,
    log_requests=settings.log_requests,
    skip_paths=parse_skip_paths(settings.log_request_skip_paths),
)
app.add_middleware(
    SecurityHeadersMiddleware,
    enabled=settings.security_headers_enabled,
    x_content_type_options=settings.security_x_content_type_options,
    x_frame_options=settings.security_x_frame_options,
    referrer_policy=settings.security_referrer_policy,
    permissions_policy=settings.security_permissions_policy,
    cross_origin_opener_policy=settings.security_cross_origin_opener_policy,
    cross_origin_resource_policy=settings.security_cross_origin_resource_policy,
    content_security_policy_enabled=settings.security_csp_enabled,
    content_security_policy=settings.security_csp_policy,
    content_security_policy_docs=settings.security_csp_docs_policy,
    content_security_policy_report_only=settings.security_csp_report_only,
    strict_transport_security_enabled=settings.security_strict_transport_security_enabled,
    strict_transport_security_max_age=settings.security_strict_transport_security_max_age,
    strict_transport_security_include_subdomains=(
        settings.security_strict_transport_security_include_subdomains
    ),
    strict_transport_security_preload=settings.security_strict_transport_security_preload,
)
app.include_router(api_router)
app.include_router(media_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    if await check_database():
        return {"status": "ok"}
    raise HTTPException(status_code=500, detail="database unavailable")


def _configure_frontend_routes(application: FastAPI) -> None:
    if not settings.frontend_enabled:
        return

    dist_dir = Path(settings.frontend_dist_dir)
    index_file = dist_dir / "index.html"

    if not index_file.is_file():
        return

    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        application.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @application.get("/", include_in_schema=False)
    async def frontend_index() -> FileResponse:
        return FileResponse(index_file)

    @application.get("/{full_path:path}", include_in_schema=False)
    async def frontend_entry(full_path: str) -> FileResponse:
        normalized = full_path.lstrip("/")
        if normalized in {"healthz", "api"} or normalized.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        candidate = (dist_dir / normalized).resolve()
        try:
            candidate.relative_to(dist_dir.resolve())
        except ValueError as error:
            raise HTTPException(status_code=404, detail="Not Found") from error

        if candidate.is_file():
            return FileResponse(candidate)

        return FileResponse(index_file)


_configure_frontend_routes(app)
