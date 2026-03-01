from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import QueueItemStatus, RunTriggerType, ScholarProfile, UserSetting
from app.db.session import get_session_factory
from app.logging_utils import structured_log
from app.services.ingestion import queue as queue_service
from app.services.ingestion.application import (
    RunAlreadyInProgressError,
    RunBlockedBySafetyPolicyError,
    ScholarIngestionService,
)
from app.services.scholar.source import LiveScholarSource
from app.settings import settings

logger = logging.getLogger(__name__)


def effective_request_delay_seconds(value: int | None, *, floor: int) -> int:
    try:
        parsed = int(value) if value is not None else floor
    except (TypeError, ValueError):
        parsed = floor
    return max(floor, parsed)


class QueueJobRunner:
    def __init__(
        self,
        *,
        tick_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
        continuation_queue_enabled: bool,
        continuation_base_delay_seconds: int,
        continuation_max_delay_seconds: int,
        continuation_max_attempts: int,
        queue_batch_size: int,
    ) -> None:
        self._tick_seconds = tick_seconds
        self._network_error_retries = network_error_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._max_pages_per_scholar = max_pages_per_scholar
        self._page_size = page_size
        self._continuation_queue_enabled = continuation_queue_enabled
        self._continuation_base_delay_seconds = continuation_base_delay_seconds
        self._continuation_max_delay_seconds = continuation_max_delay_seconds
        self._continuation_max_attempts = continuation_max_attempts
        self._queue_batch_size = queue_batch_size
        self._source = LiveScholarSource()

    async def drain_continuation_queue(self) -> None:
        now = datetime.now(UTC)
        session_factory = get_session_factory()
        async with session_factory() as session:
            jobs = await queue_service.list_due_jobs(
                session,
                now=now,
                limit=self._queue_batch_size,
            )
        for job in jobs:
            await self._run_queue_job(job)

    async def _drop_queue_job_if_max_attempts(
        self,
        job: queue_service.ContinuationQueueJob,
    ) -> bool:
        if job.attempt_count < self._continuation_max_attempts:
            return False
        session_factory = get_session_factory()
        async with session_factory() as session:
            dropped = await queue_service.mark_dropped(
                session,
                job_id=job.id,
                reason="max_attempts_reached",
            )
            await session.commit()
        if dropped is not None:
            structured_log(
                logger,
                "warning",
                "scheduler.queue_item_dropped_max_attempts",
                queue_item_id=job.id,
                user_id=job.user_id,
                scholar_profile_id=job.scholar_profile_id,
                attempt_count=job.attempt_count,
                max_attempts=self._continuation_max_attempts,
            )
        return True

    async def _mark_queue_job_retrying(
        self,
        job: queue_service.ContinuationQueueJob,
    ) -> bool:
        session_factory = get_session_factory()
        async with session_factory() as session:
            queue_item = await queue_service.mark_retrying(session, job_id=job.id)
            await session.commit()
        if queue_item is None:
            return False
        return queue_item.status != QueueItemStatus.DROPPED.value

    async def _queue_job_has_available_scholar(
        self,
        job: queue_service.ContinuationQueueJob,
    ) -> bool:
        session_factory = get_session_factory()
        async with session_factory() as session:
            scholar_result = await session.execute(
                select(ScholarProfile.id).where(
                    ScholarProfile.user_id == job.user_id,
                    ScholarProfile.id == job.scholar_profile_id,
                    ScholarProfile.is_enabled.is_(True),
                )
            )
            scholar_id = scholar_result.scalar_one_or_none()
            if scholar_id is not None:
                return True
            dropped = await queue_service.mark_dropped(
                session,
                job_id=job.id,
                reason="scholar_unavailable",
            )
            await session.commit()
        if dropped is not None:
            structured_log(
                logger,
                "info",
                "scheduler.queue_item_dropped_scholar_unavailable",
                queue_item_id=job.id,
                user_id=job.user_id,
                scholar_profile_id=job.scholar_profile_id,
            )
        return False

    async def _reschedule_queue_job_lock_active(self, job: queue_service.ContinuationQueueJob) -> None:
        session_factory = get_session_factory()
        async with session_factory() as recovery_session:
            await queue_service.reschedule_job(
                recovery_session,
                job_id=job.id,
                delay_seconds=max(self._tick_seconds, 15),
                reason="user_run_lock_active",
                error="run_already_in_progress",
            )
            await recovery_session.commit()
        structured_log(
            logger,
            "info",
            "scheduler.queue_item_deferred_lock",
            queue_item_id=job.id,
            user_id=job.user_id,
        )

    async def _reschedule_queue_job_safety_cooldown(
        self,
        job: queue_service.ContinuationQueueJob,
        exc: RunBlockedBySafetyPolicyError,
    ) -> None:
        cooldown_remaining_seconds = max(
            self._tick_seconds,
            int(exc.safety_state.get("cooldown_remaining_seconds") or 0),
        )
        session_factory = get_session_factory()
        async with session_factory() as recovery_session:
            await queue_service.reschedule_job(
                recovery_session,
                job_id=job.id,
                delay_seconds=max(self._tick_seconds, cooldown_remaining_seconds),
                reason="scrape_safety_cooldown",
                error=str(exc.message),
            )
            await recovery_session.commit()
        structured_log(
            logger,
            "info",
            "scheduler.queue_item_deferred_safety_cooldown",
            queue_item_id=job.id,
            user_id=job.user_id,
            reason=exc.safety_state.get("cooldown_reason"),
            cooldown_remaining_seconds=cooldown_remaining_seconds,
        )

    async def _reschedule_queue_job_after_exception(
        self,
        job: queue_service.ContinuationQueueJob,
        *,
        exc: Exception,
    ) -> None:
        session_factory = get_session_factory()
        async with session_factory() as recovery_session:
            queue_item = await queue_service.increment_attempt_count(recovery_session, job_id=job.id)
            if queue_item is None:
                await recovery_session.commit()
                return
            if int(queue_item.attempt_count) >= self._continuation_max_attempts:
                await queue_service.mark_dropped(
                    recovery_session,
                    job_id=job.id,
                    reason="scheduler_exception_max_attempts",
                    error=str(exc),
                )
                await recovery_session.commit()
                structured_log(
                    logger,
                    "warning",
                    "scheduler.queue_item_dropped_after_exception",
                    queue_item_id=job.id,
                    user_id=job.user_id,
                    attempt_count=queue_item.attempt_count,
                )
                return
            delay_seconds = queue_service.compute_backoff_seconds(
                base_seconds=self._continuation_base_delay_seconds,
                attempt_count=int(queue_item.attempt_count),
                max_seconds=self._continuation_max_delay_seconds,
            )
            await queue_service.reschedule_job(
                recovery_session,
                job_id=job.id,
                delay_seconds=delay_seconds,
                reason="scheduler_exception",
                error=str(exc),
            )
            await recovery_session.commit()
        structured_log(
            logger,
            "exception",
            "scheduler.queue_item_run_failed",
            queue_item_id=job.id,
            user_id=job.user_id,
        )

    async def _load_request_delay_for_user(self, user_id: int, *, floor: int) -> int:
        session_factory = get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(UserSetting.request_delay_seconds).where(UserSetting.user_id == user_id)
            )
            delay = result.scalar_one_or_none()
        return effective_request_delay_seconds(delay, floor=floor)

    async def _run_ingestion_for_queue_job(
        self,
        job: queue_service.ContinuationQueueJob,
        *,
        request_delay_floor: int,
    ):
        request_delay_seconds = await self._load_request_delay_for_user(job.user_id, floor=request_delay_floor)
        session_factory = get_session_factory()
        async with session_factory() as session:
            ingestion = ScholarIngestionService(source=self._source)
            try:
                return await ingestion.run_for_user(
                    session,
                    user_id=job.user_id,
                    trigger_type=RunTriggerType.SCHEDULED,
                    request_delay_seconds=request_delay_seconds,
                    network_error_retries=self._network_error_retries,
                    retry_backoff_seconds=self._retry_backoff_seconds,
                    rate_limit_retries=settings.ingestion_rate_limit_retries,
                    rate_limit_backoff_seconds=settings.ingestion_rate_limit_backoff_seconds,
                    max_pages_per_scholar=self._max_pages_per_scholar,
                    page_size=self._page_size,
                    scholar_profile_ids={job.scholar_profile_id},
                    start_cstart_by_scholar_id={job.scholar_profile_id: job.resume_cstart},
                    auto_queue_continuations=self._continuation_queue_enabled,
                    queue_delay_seconds=self._continuation_base_delay_seconds,
                    alert_blocked_failure_threshold=settings.ingestion_alert_blocked_failure_threshold,
                    alert_network_failure_threshold=settings.ingestion_alert_network_failure_threshold,
                    alert_retry_scheduled_threshold=settings.ingestion_alert_retry_scheduled_threshold,
                )
            except RunAlreadyInProgressError:
                await session.rollback()
                await self._reschedule_queue_job_lock_active(job)
            except RunBlockedBySafetyPolicyError as exc:
                await session.rollback()
                await self._reschedule_queue_job_safety_cooldown(job, exc)
            except Exception as exc:
                await session.rollback()
                await self._reschedule_queue_job_after_exception(job, exc=exc)
        return None

    async def _finalize_successful_queue_job(self, session, job, run_summary) -> None:
        queue_item = await queue_service.reset_attempt_count(session, job_id=job.id)
        await session.commit()
        if queue_item is None:
            structured_log(
                logger,
                "info",
                "scheduler.queue_item_resolved",
                queue_item_id=job.id,
                user_id=job.user_id,
                run_id=run_summary.crawl_run_id,
                status=run_summary.status.value,
            )
            return
        structured_log(
            logger,
            "info",
            "scheduler.queue_item_progressed",
            queue_item_id=job.id,
            user_id=job.user_id,
            run_id=run_summary.crawl_run_id,
            status=run_summary.status.value,
            attempt_count=int(queue_item.attempt_count),
        )

    async def _finalize_failed_queue_job(self, session, job, run_summary) -> None:
        queue_item = await queue_service.increment_attempt_count(session, job_id=job.id)
        if queue_item is None:
            await session.commit()
            structured_log(
                logger,
                "info",
                "scheduler.queue_item_resolved",
                queue_item_id=job.id,
                user_id=job.user_id,
                run_id=run_summary.crawl_run_id,
                status=run_summary.status.value,
            )
            return
        if int(queue_item.attempt_count) >= self._continuation_max_attempts:
            await queue_service.mark_dropped(session, job_id=job.id, reason="max_attempts_after_run")
            await session.commit()
            structured_log(
                logger,
                "warning",
                "scheduler.queue_item_dropped_max_attempts_after_run",
                queue_item_id=job.id,
                user_id=job.user_id,
                attempt_count=queue_item.attempt_count,
                run_id=run_summary.crawl_run_id,
                status=run_summary.status.value,
            )
            return
        delay_seconds = queue_service.compute_backoff_seconds(
            base_seconds=self._continuation_base_delay_seconds,
            attempt_count=int(queue_item.attempt_count),
            max_seconds=self._continuation_max_delay_seconds,
        )
        await queue_service.reschedule_job(
            session,
            job_id=job.id,
            delay_seconds=delay_seconds,
            reason=queue_item.reason,
            error=queue_item.last_error,
        )
        await session.commit()
        structured_log(
            logger,
            "info",
            "scheduler.queue_item_rescheduled_failed",
            queue_item_id=job.id,
            user_id=job.user_id,
            run_id=run_summary.crawl_run_id,
            status=run_summary.status.value,
            attempt_count=int(queue_item.attempt_count),
            delay_seconds=delay_seconds,
        )

    async def _finalize_queue_job_after_run(self, job: queue_service.ContinuationQueueJob, run_summary) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            if int(run_summary.failed_count) <= 0:
                await self._finalize_successful_queue_job(session, job, run_summary)
            else:
                await self._finalize_failed_queue_job(session, job, run_summary)

    async def _run_queue_job(self, job: queue_service.ContinuationQueueJob) -> None:
        if await self._drop_queue_job_if_max_attempts(job):
            return
        if not await self._mark_queue_job_retrying(job):
            return
        if not await self._queue_job_has_available_scholar(job):
            return
        from app.services.settings import application as user_settings_service

        request_delay_floor = user_settings_service.resolve_request_delay_minimum(
            settings.ingestion_min_request_delay_seconds,
        )
        run_summary = await self._run_ingestion_for_queue_job(job, request_delay_floor=request_delay_floor)
        if run_summary is None:
            return
        await self._finalize_queue_job_after_run(job, run_summary)
