from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_current_user
from app.api.errors import ApiException
from app.api.responses import success_payload
from app.api.schemas import (
    ManualRunEnvelope,
    QueueClearEnvelope,
    QueueItemEnvelope,
    QueueListEnvelope,
    RunDetailEnvelope,
    RunsListEnvelope,
)
from app.db.models import RunStatus, RunTriggerType, User
from app.db.session import get_db_session
from app.services import ingestion as ingestion_service
from app.services import runs as run_service
from app.services import user_settings as user_settings_service
from app.settings import settings
from app.api.runtime_deps import get_ingestion_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["api-runs"])

IDEMPOTENCY_HEADER = "Idempotency-Key"
IDEMPOTENCY_MAX_LENGTH = 128
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _str_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _normalize_idempotency_key(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    candidate = raw_value.strip()
    if not candidate:
        return None
    if len(candidate) > IDEMPOTENCY_MAX_LENGTH or not IDEMPOTENCY_PATTERN.match(candidate):
        raise ApiException(
            status_code=400,
            code="invalid_idempotency_key",
            message=(
                "Invalid Idempotency-Key. Use 8-128 characters from: "
                "A-Z a-z 0-9 . _ : -"
            ),
        )
    return candidate


def _serialize_run(run) -> dict[str, Any]:
    summary = run_service.extract_run_summary(run.error_log)
    return {
        "id": int(run.id),
        "trigger_type": run.trigger_type.value,
        "status": run.status.value,
        "start_dt": run.start_dt,
        "end_dt": run.end_dt,
        "scholar_count": int(run.scholar_count or 0),
        "new_publication_count": int(run.new_pub_count or 0),
        "failed_count": int(summary["failed_count"]),
        "partial_count": int(summary["partial_count"]),
    }


def _serialize_queue_item(item) -> dict[str, Any]:
    return {
        "id": int(item.id),
        "scholar_profile_id": int(item.scholar_profile_id),
        "scholar_label": item.scholar_label,
        "status": item.status,
        "reason": item.reason,
        "dropped_reason": item.dropped_reason,
        "attempt_count": int(item.attempt_count),
        "resume_cstart": int(item.resume_cstart),
        "next_attempt_dt": item.next_attempt_dt,
        "updated_at": item.updated_at,
        "last_error": item.last_error,
        "last_run_id": item.last_run_id,
    }


def _normalize_attempt_log(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "attempt": _int_value(item.get("attempt"), 0),
                "cstart": _int_value(item.get("cstart"), 0),
                "state": _str_value(item.get("state")),
                "state_reason": _str_value(item.get("state_reason")),
                "status_code": (
                    _int_value(item.get("status_code"))
                    if item.get("status_code") is not None
                    else None
                ),
                "fetch_error": _str_value(item.get("fetch_error")),
            }
        )
    return normalized


def _normalize_page_logs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        warning_codes = item.get("warning_codes")
        normalized.append(
            {
                "page": _int_value(item.get("page"), 0),
                "cstart": _int_value(item.get("cstart"), 0),
                "state": _str_value(item.get("state")) or "unknown",
                "state_reason": _str_value(item.get("state_reason")),
                "status_code": (
                    _int_value(item.get("status_code"))
                    if item.get("status_code") is not None
                    else None
                ),
                "publication_count": _int_value(item.get("publication_count"), 0),
                "attempt_count": _int_value(item.get("attempt_count"), 0),
                "has_show_more_button": _bool_value(item.get("has_show_more_button"), False),
                "articles_range": _str_value(item.get("articles_range")),
                "warning_codes": [
                    str(code)
                    for code in (warning_codes if isinstance(warning_codes, list) else [])
                ],
            }
        )
    return normalized


def _normalize_debug(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    marker_counts = value.get("marker_counts_nonzero")
    warning_codes = value.get("warning_codes")
    return {
        "status_code": (
            _int_value(value.get("status_code"))
            if value.get("status_code") is not None
            else None
        ),
        "final_url": _str_value(value.get("final_url")),
        "fetch_error": _str_value(value.get("fetch_error")),
        "body_sha256": _str_value(value.get("body_sha256")),
        "body_length": (
            _int_value(value.get("body_length"))
            if value.get("body_length") is not None
            else None
        ),
        "has_show_more_button": (
            _bool_value(value.get("has_show_more_button"), False)
            if value.get("has_show_more_button") is not None
            else None
        ),
        "articles_range": _str_value(value.get("articles_range")),
        "state_reason": _str_value(value.get("state_reason")),
        "warning_codes": [
            str(code)
            for code in (warning_codes if isinstance(warning_codes, list) else [])
        ],
        "marker_counts_nonzero": {
            str(key): _int_value(count, 0)
            for key, count in (marker_counts.items() if isinstance(marker_counts, dict) else [])
        },
        "page_logs": _normalize_page_logs(value.get("page_logs")),
        "attempt_log": _normalize_attempt_log(value.get("attempt_log")),
    }


def _normalize_scholar_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "scholar_profile_id": 0,
            "scholar_id": "unknown",
            "state": "unknown",
            "state_reason": None,
            "outcome": "failed",
            "attempt_count": 0,
            "publication_count": 0,
            "start_cstart": 0,
            "continuation_cstart": None,
            "continuation_enqueued": False,
            "continuation_cleared": False,
            "warnings": [],
            "error": None,
            "debug": None,
        }
    warnings = value.get("warnings")
    return {
        "scholar_profile_id": _int_value(value.get("scholar_profile_id"), 0),
        "scholar_id": _str_value(value.get("scholar_id")) or "unknown",
        "state": _str_value(value.get("state")) or "unknown",
        "state_reason": _str_value(value.get("state_reason")),
        "outcome": _str_value(value.get("outcome")) or "failed",
        "attempt_count": _int_value(value.get("attempt_count"), 0),
        "publication_count": _int_value(value.get("publication_count"), 0),
        "start_cstart": _int_value(value.get("start_cstart"), 0),
        "continuation_cstart": (
            _int_value(value.get("continuation_cstart"))
            if value.get("continuation_cstart") is not None
            else None
        ),
        "continuation_enqueued": _bool_value(value.get("continuation_enqueued"), False),
        "continuation_cleared": _bool_value(value.get("continuation_cleared"), False),
        "warnings": [str(item) for item in (warnings if isinstance(warnings, list) else [])],
        "error": _str_value(value.get("error")),
        "debug": _normalize_debug(value.get("debug")),
    }


def _manual_run_payload_from_run(
    run,
    *,
    idempotency_key: str | None,
    reused_existing_run: bool,
) -> dict[str, Any]:
    summary = run_service.extract_run_summary(run.error_log)
    return {
        "run_id": int(run.id),
        "status": run.status.value,
        "scholar_count": int(run.scholar_count or 0),
        "succeeded_count": int(summary["succeeded_count"]),
        "failed_count": int(summary["failed_count"]),
        "partial_count": int(summary["partial_count"]),
        "new_publication_count": int(run.new_pub_count or 0),
        "reused_existing_run": reused_existing_run,
        "idempotency_key": idempotency_key,
    }


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
    return success_payload(
        request,
        data={
            "runs": [_serialize_run(run) for run in runs],
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
    return success_payload(
        request,
        data={
            "run": _serialize_run(run),
            "summary": run_service.extract_run_summary(error_log),
            "scholar_results": [_normalize_scholar_result(item) for item in scholar_results],
        },
    )


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
    idempotency_key = _normalize_idempotency_key(request.headers.get(IDEMPOTENCY_HEADER))
    if idempotency_key is not None:
        previous_run = await run_service.get_manual_run_by_idempotency_key(
            db_session,
            user_id=current_user.id,
            idempotency_key=idempotency_key,
        )
        if previous_run is not None:
            if previous_run.status == RunStatus.RUNNING:
                raise ApiException(
                    status_code=409,
                    code="run_in_progress",
                    message="A run with this idempotency key is still in progress.",
                    details={
                        "run_id": int(previous_run.id),
                        "idempotency_key": idempotency_key,
                    },
                )
            return success_payload(
                request,
                data=_manual_run_payload_from_run(
                    previous_run,
                    idempotency_key=idempotency_key,
                    reused_existing_run=True,
                ),
            )

    user_settings = await user_settings_service.get_or_create_settings(
        db_session,
        user_id=current_user.id,
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
            idempotency_key=idempotency_key,
        )
    except ingestion_service.RunAlreadyInProgressError as exc:
        await db_session.rollback()
        raise ApiException(
            status_code=409,
            code="run_in_progress",
            message="A run is already in progress for this account.",
        ) from exc
    except IntegrityError as exc:
        await db_session.rollback()
        if idempotency_key is not None:
            existing_run = await run_service.get_manual_run_by_idempotency_key(
                db_session,
                user_id=current_user.id,
                idempotency_key=idempotency_key,
            )
            if existing_run is not None:
                if existing_run.status == RunStatus.RUNNING:
                    raise ApiException(
                        status_code=409,
                        code="run_in_progress",
                        message="A run with this idempotency key is still in progress.",
                        details={
                            "run_id": int(existing_run.id),
                            "idempotency_key": idempotency_key,
                        },
                    ) from exc
                return success_payload(
                    request,
                    data=_manual_run_payload_from_run(
                        existing_run,
                        idempotency_key=idempotency_key,
                        reused_existing_run=True,
                    ),
                )
        logger.exception(
            "api.runs.manual_integrity_error",
            extra={
                "event": "api.runs.manual_integrity_error",
                "user_id": current_user.id,
            },
        )
        raise ApiException(
            status_code=500,
            code="manual_run_failed",
            message="Manual run failed.",
        ) from exc
    except Exception as exc:
        await db_session.rollback()
        logger.exception(
            "api.runs.manual_failed",
            extra={
                "event": "api.runs.manual_failed",
                "user_id": current_user.id,
            },
        )
        raise ApiException(
            status_code=500,
            code="manual_run_failed",
            message="Manual run failed.",
        ) from exc

    return success_payload(
        request,
        data={
            "run_id": run_summary.crawl_run_id,
            "status": run_summary.status.value,
            "scholar_count": run_summary.scholar_count,
            "succeeded_count": run_summary.succeeded_count,
            "failed_count": run_summary.failed_count,
            "partial_count": run_summary.partial_count,
            "new_publication_count": run_summary.new_publication_count,
            "reused_existing_run": False,
            "idempotency_key": idempotency_key,
        },
    )


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
            "queue_items": [_serialize_queue_item(item) for item in items],
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
        data=_serialize_queue_item(queue_item),
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
        data=_serialize_queue_item(dropped),
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
