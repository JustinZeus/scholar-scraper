from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api.errors import register_api_exception_handlers
from app.api.router import router as api_router
from app.db.session import close_engine
from app.logging_config import configure_logging, parse_redact_fields
from app.security.csrf import CSRFMiddleware
from app.services.scheduler import SchedulerService
from app.settings import settings
from app.web import common as web_common
from app.web.deps import get_ingestion_service, get_scholar_source
from app.web.middleware import RequestLoggingMiddleware, parse_skip_paths
from app.web.routers import (
    admin,
    auth,
    dashboard,
    health,
    publications,
    runs,
    scholars,
    settings as settings_router,
)

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


@asynccontextmanager
async def lifespan(_: FastAPI):
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
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(api_router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(scholars.router)
app.include_router(settings_router.router)
app.include_router(runs.router)
app.include_router(publications.router)
app.include_router(dashboard.router)
app.include_router(health.router)

# Backward-compatible export kept for tests and any existing local scripts.
_get_authenticated_user = web_common.get_authenticated_user
