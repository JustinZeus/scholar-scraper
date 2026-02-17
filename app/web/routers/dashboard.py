from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RunTriggerType
from app.db.session import get_db_session
from app.presentation import dashboard as dashboard_presenter
from app.services import ingestion as ingestion_service
from app.services import publications as publication_service
from app.services import runs as run_service
from app.services import user_settings as user_settings_service
from app.settings import settings
from app.theme import resolve_theme
from app.web import common
from app.web.deps import get_ingestion_service

logger = logging.getLogger(__name__)

router = APIRouter()


async def _render_dashboard_page(
    request: Request,
    *,
    db_session: AsyncSession,
    current_user,
    theme_name: str,
    notice: str | None = None,
    page_error: str | None = None,
) -> HTMLResponse:
    unread_publications = await publication_service.list_new_for_latest_run_for_user(
        db_session,
        user_id=current_user.id,
        limit=50,
    )
    recent_runs = await run_service.list_recent_runs_for_user(
        db_session,
        user_id=current_user.id,
        limit=20,
    )
    user_settings = await user_settings_service.get_or_create_settings(
        db_session,
        user_id=current_user.id,
    )
    queue_counts = await run_service.queue_status_counts_for_user(
        db_session,
        user_id=current_user.id,
    )
    context = common.build_template_context(
        request,
        page_title="Dashboard",
        active_nav="home",
        theme_name=theme_name,
        session_user=common.to_session_user(current_user),
        notice=notice,
        page_error=page_error,
    )
    context["dashboard"] = dashboard_presenter.build_dashboard_view_model(
        unread_publications=unread_publications,
        recent_runs=recent_runs,
        request_delay_seconds=user_settings.request_delay_seconds,
        queue_counts=queue_counts,
    )
    return common.templates.TemplateResponse(
        request=request,
        name="index.html",
        context=context,
    )


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    theme: str | None = None,
    db_session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()
    return await _render_dashboard_page(
        request,
        db_session=db_session,
        current_user=current_user,
        theme_name=resolve_theme(theme),
        notice=request.query_params.get("notice"),
        page_error=request.query_params.get("error"),
    )


@router.post("/runs/manual")
async def run_manual_ingestion(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    ingest_service: ingestion_service.ScholarIngestionService = Depends(get_ingestion_service),
):
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()

    user_settings = await user_settings_service.get_or_create_settings(
        db_session,
        user_id=current_user.id,
    )
    logger.info(
        "runs.manual_started",
        extra={
            "event": "runs.manual_started",
            "user_id": current_user.id,
            "request_delay_seconds": user_settings.request_delay_seconds,
            "network_error_retries": settings.ingestion_network_error_retries,
            "max_pages_per_scholar": settings.ingestion_max_pages_per_scholar,
            "page_size": settings.ingestion_page_size,
        },
    )
    try:
        run_summary = await ingest_service.run_for_user(
            db_session,
            user_id=current_user.id,
            trigger_type=RunTriggerType.MANUAL,
            request_delay_seconds=user_settings.request_delay_seconds,
            network_error_retries=settings.ingestion_network_error_retries,
            retry_backoff_seconds=settings.ingestion_retry_backoff_seconds,
            max_pages_per_scholar=settings.ingestion_max_pages_per_scholar,
            page_size=settings.ingestion_page_size,
            auto_queue_continuations=settings.ingestion_continuation_queue_enabled,
            queue_delay_seconds=settings.ingestion_continuation_base_delay_seconds,
        )
    except ingestion_service.RunAlreadyInProgressError:
        await db_session.rollback()
        return common.redirect_with_message(
            "/",
            error="A run is already in progress for this account.",
        )
    except Exception:
        await db_session.rollback()
        logger.exception(
            "runs.manual_failed",
            extra={
                "event": "runs.manual_failed",
                "user_id": current_user.id,
            },
        )
        return common.redirect_with_message("/", error="Manual run failed. Check logs for details.")

    logger.info(
        "runs.manual_completed",
        extra={
            "event": "runs.manual_completed",
            "user_id": current_user.id,
            "run_id": run_summary.crawl_run_id,
            "status": run_summary.status.value,
            "scholar_count": run_summary.scholar_count,
            "new_publication_count": run_summary.new_publication_count,
        },
    )
    return common.redirect_with_message(
        "/",
        notice=(
            f"Run #{run_summary.crawl_run_id} complete ({run_summary.status.value}). "
            f"Scholars: {run_summary.scholar_count}, "
            f"new publications: {run_summary.new_publication_count}."
        ),
    )
