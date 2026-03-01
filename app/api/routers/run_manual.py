from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiException
from app.api.responses import success_payload
from app.api.routers.run_serializers import manual_run_payload_from_run
from app.db.models import RunStatus, RunTriggerType
from app.logging_utils import structured_log
from app.services.ingestion import application as ingestion_service
from app.services.ingestion import safety as run_safety_service
from app.services.runs import application as run_service
from app.services.settings import application as user_settings_service
from app.settings import settings

logger = logging.getLogger(__name__)


async def load_safety_state(
    db_session: AsyncSession,
    *,
    user_id: int,
) -> dict[str, Any]:
    user_settings = await user_settings_service.get_or_create_settings(
        db_session,
        user_id=user_id,
    )
    previous_safety_state = run_safety_service.get_safety_event_context(user_settings)
    if run_safety_service.clear_expired_cooldown(user_settings):
        await db_session.commit()
        await db_session.refresh(user_settings)
        structured_log(
            logger,
            "info",
            "api.runs.safety_cooldown_cleared",
            user_id=user_id,
            reason=previous_safety_state.get("cooldown_reason"),
            cooldown_until=previous_safety_state.get("cooldown_until"),
        )
    return run_safety_service.get_safety_state_payload(user_settings)


def raise_manual_runs_disabled(*, user_id: int, safety_state: dict[str, Any]) -> None:
    structured_log(
        logger,
        "warning",
        "api.runs.manual_blocked_policy",
        user_id=user_id,
        policy={"manual_run_allowed": False},
        safety_state=safety_state,
    )
    raise ApiException(
        status_code=403,
        code="manual_runs_disabled",
        message="Manual checks are disabled by server policy.",
        details={
            "policy": {"manual_run_allowed": False},
            "safety_state": safety_state,
        },
    )


async def reused_manual_run_payload(
    db_session: AsyncSession,
    *,
    request: Request,
    user_id: int,
    idempotency_key: str | None,
    safety_state: dict[str, Any],
) -> dict[str, Any] | None:
    if idempotency_key is None:
        return None
    previous_run = await run_service.get_manual_run_by_idempotency_key(
        db_session,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )
    if previous_run is None:
        return None
    if previous_run.status in (RunStatus.RUNNING, RunStatus.RESOLVING):
        raise ApiException(
            status_code=409,
            code="run_in_progress",
            message="A run with this idempotency key is still in progress.",
            details={"run_id": int(previous_run.id), "idempotency_key": idempotency_key},
        )
    return success_payload(
        request,
        data=manual_run_payload_from_run(
            previous_run,
            idempotency_key=idempotency_key,
            reused_existing_run=True,
            safety_state=safety_state,
        ),
    )


async def run_ingestion_for_manual(
    db_session: AsyncSession,
    *,
    ingest_service: ingestion_service.ScholarIngestionService,
    user_id: int,
    idempotency_key: str | None,
):
    user_settings = await user_settings_service.get_or_create_settings(
        db_session,
        user_id=user_id,
    )
    return await ingest_service.run_for_user(
        db_session,
        user_id=user_id,
        trigger_type=RunTriggerType.MANUAL,
        request_delay_seconds=user_settings.request_delay_seconds,
        network_error_retries=settings.ingestion_network_error_retries,
        retry_backoff_seconds=settings.ingestion_retry_backoff_seconds,
        max_pages_per_scholar=settings.ingestion_max_pages_per_scholar,
        page_size=settings.ingestion_page_size,
        auto_queue_continuations=settings.ingestion_continuation_queue_enabled,
        queue_delay_seconds=settings.ingestion_continuation_base_delay_seconds,
        idempotency_key=idempotency_key,
        alert_blocked_failure_threshold=settings.ingestion_alert_blocked_failure_threshold,
        alert_network_failure_threshold=settings.ingestion_alert_network_failure_threshold,
        alert_retry_scheduled_threshold=settings.ingestion_alert_retry_scheduled_threshold,
    )


async def recover_integrity_error(
    db_session: AsyncSession,
    *,
    request: Request,
    user_id: int,
    idempotency_key: str | None,
    original_exc: IntegrityError,
) -> dict[str, Any]:
    if idempotency_key is None:
        structured_log(
            logger,
            "exception",
            "api.runs.manual_integrity_error",
            user_id=user_id,
        )
        raise ApiException(status_code=500, code="manual_run_failed", message="Manual run failed.") from original_exc
    existing_run = await run_service.get_manual_run_by_idempotency_key(
        db_session,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )
    if existing_run is None:
        structured_log(
            logger,
            "exception",
            "api.runs.manual_integrity_error",
            user_id=user_id,
        )
        raise ApiException(status_code=500, code="manual_run_failed", message="Manual run failed.") from original_exc
    if existing_run.status in (RunStatus.RUNNING, RunStatus.RESOLVING):
        raise ApiException(
            status_code=409,
            code="run_in_progress",
            message="A run with this idempotency key is still in progress.",
            details={"run_id": int(existing_run.id), "idempotency_key": idempotency_key},
        ) from original_exc
    return success_payload(
        request,
        data=manual_run_payload_from_run(
            existing_run,
            idempotency_key=idempotency_key,
            reused_existing_run=True,
            safety_state=await load_safety_state(db_session, user_id=user_id),
        ),
    )


async def execute_manual_run(
    db_session: AsyncSession,
    *,
    request: Request,
    ingest_service: ingestion_service.ScholarIngestionService,
    user_id: int,
    idempotency_key: str | None,
):
    try:
        return await run_ingestion_for_manual(
            db_session,
            ingest_service=ingest_service,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
    except ingestion_service.RunAlreadyInProgressError as exc:
        await db_session.rollback()
        raise ApiException(
            status_code=409,
            code="run_in_progress",
            message="A run is already in progress for this account.",
        ) from exc
    except ingestion_service.RunBlockedBySafetyPolicyError as exc:
        await db_session.rollback()
        raise_manual_blocked_safety(exc=exc, user_id=user_id)
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


def raise_manual_blocked_safety(*, exc, user_id: int) -> None:
    structured_log(
        logger,
        "info",
        "api.runs.manual_blocked_safety",
        user_id=user_id,
        reason=exc.safety_state.get("cooldown_reason"),
        cooldown_until=exc.safety_state.get("cooldown_until"),
        cooldown_remaining_seconds=exc.safety_state.get("cooldown_remaining_seconds"),
    )
    raise ApiException(
        status_code=429,
        code=exc.code,
        message=exc.message,
        details={"safety_state": exc.safety_state},
    ) from exc


def raise_manual_failed(*, exc: Exception, user_id: int) -> None:
    structured_log(
        logger,
        "exception",
        "api.runs.manual_failed",
        user_id=user_id,
    )
    raise ApiException(status_code=500, code="manual_run_failed", message="Manual run failed.") from exc
