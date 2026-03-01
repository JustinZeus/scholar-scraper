from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_current_user
from app.api.errors import ApiException
from app.api.responses import success_payload
from app.api.routers.run_manual import (
    load_safety_state,
    raise_manual_blocked_safety,
    raise_manual_failed,
    raise_manual_runs_disabled,
    recover_integrity_error,
    reused_manual_run_payload,
)
from app.api.routers.run_serializers import (
    IDEMPOTENCY_HEADER,
    normalize_idempotency_key,
    normalize_scholar_result,
    serialize_queue_item,
    serialize_run,
)
from app.api.runtime_deps import get_ingestion_service
from app.api.schemas import (
    ManualRunEnvelope,
    QueueClearEnvelope,
    QueueItemEnvelope,
    QueueListEnvelope,
    RunDetailEnvelope,
    RunsListEnvelope,
)
from app.db.models import RunStatus, RunTriggerType, User
from app.db.session import get_db_session, get_session_factory
from app.logging_utils import structured_log
from app.services.ingestion import application as ingestion_service
from app.services.runs import application as run_service
from app.services.runs.events import event_generator
from app.services.settings import application as user_settings_service
from app.settings import settings

logger = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task[Any]] = set()


def _drop_finished_task(task: asyncio.Task[Any]) -> None:
    _background_tasks.discard(task)
    try:
        task.result()
    except Exception:
        structured_log(logger, "exception", "runs.background_task_failed")

router = APIRouter(prefix="/runs", tags=["api-runs"])
ACTIVE_RUN_STATUSES = {RunStatus.RUNNING, RunStatus.RESOLVING}


@router.get(
    "",
    response_model=RunsListEnvelope,
)
async def list_runs(
    request: Request,
    failed_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    runs = await run_service.list_runs_for_user(
        db_session,
        user_id=current_user.id,
        limit=limit,
        failed_only=failed_only,
    )
    safety_state = await load_safety_state(
        db_session,
        user_id=current_user.id,
    )
    return success_payload(
        request,
        data={
            "runs": [serialize_run(run) for run in runs],
            "safety_state": safety_state,
        },
    )


@router.get(
    "/{run_id}",
    response_model=RunDetailEnvelope,
)
async def get_run(
    run_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    run = await run_service.get_run_for_user(
        db_session,
        user_id=current_user.id,
        run_id=run_id,
    )
    if run is None:
        raise ApiException(
            status_code=404,
            code="run_not_found",
            message="Run not found.",
        )
    error_log = run.error_log if isinstance(run.error_log, dict) else {}
    scholar_results = error_log.get("scholar_results")
    if not isinstance(scholar_results, list):
        scholar_results = []
    safety_state = await load_safety_state(
        db_session,
        user_id=current_user.id,
    )
    return success_payload(
        request,
        data={
            "run": serialize_run(run),
            "summary": run_service.extract_run_summary(error_log),
            "scholar_results": [normalize_scholar_result(item) for item in scholar_results],
            "safety_state": safety_state,
        },
    )


@router.post(
    "/{run_id}/cancel",
    response_model=RunDetailEnvelope,
)
async def cancel_run(
    run_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    run = await run_service.get_run_for_user(
        db_session,
        user_id=current_user.id,
        run_id=run_id,
    )
    if run is None:
        raise ApiException(
            status_code=404,
            code="run_not_found",
            message="Run not found.",
        )

    if run.status in ACTIVE_RUN_STATUSES:
        run.status = RunStatus.CANCELED
        await db_session.commit()
        await db_session.refresh(run)
    else:
        raise ApiException(
            status_code=409,
            code="run_not_cancelable",
            message="Run is already terminal and cannot be canceled.",
            details={"run_id": int(run.id), "status": run.status.value},
        )

    error_log = run.error_log if isinstance(run.error_log, dict) else {}
    scholar_results = error_log.get("scholar_results")
    if not isinstance(scholar_results, list):
        scholar_results = []

    safety_state = await load_safety_state(
        db_session,
        user_id=current_user.id,
    )

    return success_payload(
        request,
        data={
            "run": serialize_run(run),
            "summary": run_service.extract_run_summary(error_log),
            "scholar_results": [normalize_scholar_result(item) for item in scholar_results],
            "safety_state": safety_state,
        },
    )


async def _start_manual_run(
    db_session: AsyncSession,
    *,
    current_user: User,
    ingest_service: ingestion_service.ScholarIngestionService,
    idempotency_key: str | None,
) -> tuple[Any, Any, list, dict]:
    user_settings = await user_settings_service.get_or_create_settings(db_session, user_id=current_user.id)
    run, scholars, start_cstart_map = await ingest_service.initialize_run(
        db_session,
        user_id=current_user.id,
        trigger_type=RunTriggerType.MANUAL,
        request_delay_seconds=user_settings.request_delay_seconds,
        network_error_retries=settings.ingestion_network_error_retries,
        retry_backoff_seconds=settings.ingestion_retry_backoff_seconds,
        max_pages_per_scholar=settings.ingestion_max_pages_per_scholar,
        page_size=settings.ingestion_page_size,
        idempotency_key=idempotency_key,
        alert_blocked_failure_threshold=settings.ingestion_alert_blocked_failure_threshold,
        alert_network_failure_threshold=settings.ingestion_alert_network_failure_threshold,
        alert_retry_scheduled_threshold=settings.ingestion_alert_retry_scheduled_threshold,
    )
    return user_settings, run, scholars, start_cstart_map


def _spawn_background_execution(
    ingest_service: ingestion_service.ScholarIngestionService,
    *,
    run: Any,
    current_user: User,
    scholars: list,
    start_cstart_map: dict,
    user_settings: Any,
    idempotency_key: str | None,
) -> None:
    from app.db.session import get_session_factory

    task = asyncio.create_task(
        ingest_service.execute_run(
            session_factory=get_session_factory(),
            run_id=run.id,
            user_id=current_user.id,
            scholars=scholars,
            start_cstart_map=start_cstart_map,
            request_delay_seconds=user_settings.request_delay_seconds,
            network_error_retries=settings.ingestion_network_error_retries,
            retry_backoff_seconds=settings.ingestion_retry_backoff_seconds,
            max_pages_per_scholar=settings.ingestion_max_pages_per_scholar,
            page_size=settings.ingestion_page_size,
            auto_queue_continuations=settings.ingestion_continuation_queue_enabled,
            queue_delay_seconds=settings.ingestion_continuation_base_delay_seconds,
            alert_blocked_failure_threshold=settings.ingestion_alert_blocked_failure_threshold,
            alert_network_failure_threshold=settings.ingestion_alert_network_failure_threshold,
            alert_retry_scheduled_threshold=settings.ingestion_alert_retry_scheduled_threshold,
            idempotency_key=idempotency_key,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_drop_finished_task)


@router.post(
    "/manual",
    response_model=ManualRunEnvelope,
)
async def run_manual(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
    ingest_service: ingestion_service.ScholarIngestionService = Depends(get_ingestion_service),
):
    user_id = int(current_user.id)
    safety_state = await load_safety_state(db_session, user_id=user_id)
    if not settings.ingestion_manual_run_allowed:
        raise_manual_runs_disabled(user_id=user_id, safety_state=safety_state)

    idempotency_key = normalize_idempotency_key(request.headers.get(IDEMPOTENCY_HEADER))
    reused_payload = await reused_manual_run_payload(
        db_session,
        request=request,
        user_id=user_id,
        idempotency_key=idempotency_key,
        safety_state=safety_state,
    )
    if reused_payload is not None:
        return reused_payload

    try:
        user_settings, run, scholars, start_cstart_map = await _start_manual_run(
            db_session,
            current_user=current_user,
            ingest_service=ingest_service,
            idempotency_key=idempotency_key,
        )
        await db_session.commit()
        _spawn_background_execution(
            ingest_service,
            run=run,
            current_user=current_user,
            scholars=scholars,
            start_cstart_map=start_cstart_map,
            user_settings=user_settings,
            idempotency_key=idempotency_key,
        )
        return success_payload(
            request,
            data={
                "run_id": int(run.id),
                "status": run.status.value,
                "scholar_count": int(run.scholar_count or 0),
                "succeeded_count": 0,
                "failed_count": 0,
                "partial_count": 0,
                "new_publication_count": 0,
                "reused_existing_run": False,
                "idempotency_key": idempotency_key,
                "safety_state": await load_safety_state(db_session, user_id=user_id),
            },
        )
    except ingestion_service.RunBlockedBySafetyPolicyError as exc:
        await db_session.rollback()
        raise_manual_blocked_safety(exc=exc, user_id=user_id)
    except ingestion_service.RunAlreadyInProgressError as exc:
        await db_session.rollback()
        raise ApiException(
            status_code=409,
            code="run_in_progress",
            message="A run is already in progress for this account.",
        ) from exc
    except IntegrityError as exc:
        await db_session.rollback()
        return await recover_integrity_error(
            db_session,
            request=request,
            user_id=user_id,
            idempotency_key=idempotency_key,
            original_exc=exc,
        )
    except Exception as exc:
        await db_session.rollback()
        raise_manual_failed(exc=exc, user_id=user_id)


@router.get(
    "/queue/items",
    response_model=QueueListEnvelope,
)
async def list_queue_items(
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    items = await run_service.list_queue_items_for_user(
        db_session,
        user_id=current_user.id,
        limit=limit,
    )
    return success_payload(
        request,
        data={
            "queue_items": [serialize_queue_item(item) for item in items],
        },
    )


@router.post(
    "/queue/{queue_item_id}/retry",
    response_model=QueueItemEnvelope,
)
async def retry_queue_item(
    queue_item_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    try:
        queue_item = await run_service.retry_queue_item_for_user(
            db_session,
            user_id=current_user.id,
            queue_item_id=queue_item_id,
        )
    except run_service.QueueTransitionError as exc:
        raise ApiException(
            status_code=409,
            code=exc.code,
            message=exc.message,
            details={"current_status": exc.current_status},
        ) from exc
    if queue_item is None:
        raise ApiException(
            status_code=404,
            code="queue_item_not_found",
            message="Queue item not found.",
        )
    return success_payload(
        request,
        data=serialize_queue_item(queue_item),
    )


@router.post(
    "/queue/{queue_item_id}/drop",
    response_model=QueueItemEnvelope,
)
async def drop_queue_item(
    queue_item_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    try:
        dropped = await run_service.drop_queue_item_for_user(
            db_session,
            user_id=current_user.id,
            queue_item_id=queue_item_id,
        )
    except run_service.QueueTransitionError as exc:
        raise ApiException(
            status_code=409,
            code=exc.code,
            message=exc.message,
            details={"current_status": exc.current_status},
        ) from exc
    if dropped is None:
        raise ApiException(
            status_code=404,
            code="queue_item_not_found",
            message="Queue item not found.",
        )
    return success_payload(
        request,
        data=serialize_queue_item(dropped),
    )


@router.delete(
    "/queue/{queue_item_id}",
    response_model=QueueClearEnvelope,
)
async def clear_queue_item(
    queue_item_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    try:
        deleted = await run_service.clear_queue_item_for_user(
            db_session,
            user_id=current_user.id,
            queue_item_id=queue_item_id,
        )
    except run_service.QueueTransitionError as exc:
        raise ApiException(
            status_code=409,
            code=exc.code,
            message=exc.message,
            details={"current_status": exc.current_status},
        ) from exc
    if deleted is None:
        raise ApiException(
            status_code=404,
            code="queue_item_not_found",
            message="Queue item not found.",
        )
    return success_payload(
        request,
        data={
            "queue_item_id": deleted.queue_item_id,
            "previous_status": deleted.previous_status,
            "status": "cleared",
            "message": "Queue item cleared.",
        },
    )


@router.get("/{run_id}/stream")
async def stream_run_events(
    run_id: int,
    current_user: User = Depends(get_api_current_user),
):
    session_factory = get_session_factory()
    async with session_factory() as db_session:
        run = await run_service.get_run_for_user(
            db_session,
            user_id=current_user.id,
            run_id=run_id,
        )
    if run is None:
        raise ApiException(
            status_code=404,
            code="run_not_found",
            message="Run not found.",
        )
    return StreamingResponse(event_generator(run_id), media_type="text/event-stream")
