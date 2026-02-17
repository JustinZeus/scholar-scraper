from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.services import runs as run_service
from app.theme import resolve_theme
from app.web import common

router = APIRouter()


def _as_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _status_badge(status_value: str) -> str:
    if status_value == "success":
        return "ok"
    if status_value == "failed":
        return "danger"
    return "warn"


def _queue_status_badge(status_value: str) -> str:
    if status_value == "dropped":
        return "danger"
    if status_value == "retrying":
        return "ok"
    return "warn"


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _summary_dict(error_log: object) -> dict[str, object]:
    if not isinstance(error_log, dict):
        return {}
    summary = error_log.get("summary")
    if not isinstance(summary, dict):
        return {}
    return summary


@router.get("/runs", response_class=HTMLResponse)
async def runs_page(
    request: Request,
    theme: str | None = None,
    failed_only: str | None = None,
    db_session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()

    failed_only_enabled = _as_bool(failed_only)
    runs = await run_service.list_runs_for_user(
        db_session,
        user_id=current_user.id,
        limit=200,
        failed_only=failed_only_enabled,
    )

    run_items = []
    for run in runs:
        summary = _summary_dict(run.error_log)
        failed_count = summary.get("failed_count", 0)
        partial_count = summary.get("partial_count", 0)
        run_items.append(
            {
                "id": run.id,
                "started_at": _format_dt(run.start_dt),
                "finished_at": _format_dt(run.end_dt),
                "status": run.status.value,
                "status_badge": _status_badge(run.status.value),
                "trigger_type": run.trigger_type.value,
                "scholar_count": run.scholar_count,
                "new_publication_count": run.new_pub_count,
                "failed_count": failed_count,
                "partial_count": partial_count,
            }
        )

    queue_entries = await run_service.list_queue_items_for_user(
        db_session,
        user_id=current_user.id,
        limit=200,
    )
    queue_items = []
    for item in queue_entries:
        queue_items.append(
            {
                "id": item.id,
                "scholar_profile_id": item.scholar_profile_id,
                "scholar_label": item.scholar_label,
                "status": item.status,
                "status_badge": _queue_status_badge(item.status),
                "reason": item.reason,
                "dropped_reason": item.dropped_reason,
                "attempt_count": item.attempt_count,
                "resume_cstart": item.resume_cstart,
                "next_attempt_at": _format_dt(item.next_attempt_dt),
                "updated_at": _format_dt(item.updated_at),
                "last_error": item.last_error,
                "last_run_id": item.last_run_id,
            }
        )

    context = common.build_template_context(
        request,
        page_title="Runs",
        active_nav="runs",
        theme_name=resolve_theme(theme),
        session_user=common.to_session_user(current_user),
        notice=request.query_params.get("notice"),
        page_error=request.query_params.get("error"),
    )
    context["runs"] = run_items
    context["failed_only"] = failed_only_enabled
    context["queue_items"] = queue_items
    return common.templates.TemplateResponse(
        request=request,
        name="runs.html",
        context=context,
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail_page(
    request: Request,
    run_id: int,
    theme: str | None = None,
    db_session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()

    run = await run_service.get_run_for_user(
        db_session,
        user_id=current_user.id,
        run_id=run_id,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")

    error_log = run.error_log if isinstance(run.error_log, dict) else {}
    scholar_results = error_log.get("scholar_results", [])
    if not isinstance(scholar_results, list):
        scholar_results = []

    context = common.build_template_context(
        request,
        page_title=f"Run #{run.id}",
        active_nav="runs",
        theme_name=resolve_theme(theme),
        session_user=common.to_session_user(current_user),
    )
    context["run"] = {
        "id": run.id,
        "started_at": _format_dt(run.start_dt),
        "finished_at": _format_dt(run.end_dt),
        "status": run.status.value,
        "status_badge": _status_badge(run.status.value),
        "trigger_type": run.trigger_type.value,
        "scholar_count": run.scholar_count,
        "new_publication_count": run.new_pub_count,
    }
    context["run_summary"] = _summary_dict(error_log)
    context["scholar_results"] = scholar_results
    return common.templates.TemplateResponse(
        request=request,
        name="run_detail.html",
        context=context,
    )


@router.post("/runs/queue/{queue_item_id}/drop")
async def drop_queue_item(
    request: Request,
    queue_item_id: int,
    db_session: AsyncSession = Depends(get_db_session),
):
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()

    try:
        dropped = await run_service.drop_queue_item_for_user(
            db_session,
            user_id=current_user.id,
            queue_item_id=queue_item_id,
        )
    except run_service.QueueTransitionError as exc:
        return common.redirect_with_message(
            "/runs",
            error=f"Queue item #{queue_item_id}: {exc.message}",
        )
    if dropped is None:
        raise HTTPException(status_code=404, detail="Queue item not found.")
    return common.redirect_with_message(
        "/runs",
        notice=f"Queue item #{queue_item_id} marked as dropped.",
    )


@router.post("/runs/queue/{queue_item_id}/clear")
async def clear_queue_item(
    request: Request,
    queue_item_id: int,
    db_session: AsyncSession = Depends(get_db_session),
):
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()

    try:
        cleared = await run_service.clear_queue_item_for_user(
            db_session,
            user_id=current_user.id,
            queue_item_id=queue_item_id,
        )
    except run_service.QueueTransitionError as exc:
        return common.redirect_with_message(
            "/runs",
            error=f"Queue item #{queue_item_id}: {exc.message}",
        )
    if cleared is None:
        raise HTTPException(status_code=404, detail="Queue item not found.")
    return common.redirect_with_message(
        "/runs",
        notice=f"Queue item #{queue_item_id} cleared.",
    )


@router.post("/runs/queue/{queue_item_id}/retry")
async def retry_queue_item(
    request: Request,
    queue_item_id: int,
    db_session: AsyncSession = Depends(get_db_session),
):
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()

    try:
        queue_item = await run_service.retry_queue_item_for_user(
            db_session,
            user_id=current_user.id,
            queue_item_id=queue_item_id,
        )
    except run_service.QueueTransitionError as exc:
        return common.redirect_with_message(
            "/runs",
            error=f"Queue item #{queue_item_id}: {exc.message}",
        )
    if queue_item is None:
        raise HTTPException(status_code=404, detail="Queue item not found.")
    return common.redirect_with_message(
        "/runs",
        notice=(
            f"Queue item #{queue_item_id} queued for retry "
            f"(scholar: {queue_item.scholar_label})."
        ),
    )
