from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CrawlRun,
    QueueItemStatus,
    RunTriggerType,
    ScholarProfile,
    User,
    UserSetting,
)
from app.db.session import get_session_factory
from app.services import continuation_queue as queue_service
from app.services.ingestion import RunAlreadyInProgressError, ScholarIngestionService
from app.services.scholar_source import LiveScholarSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _AutoRunCandidate:
    user_id: int
    run_interval_minutes: int
    request_delay_seconds: int


class SchedulerService:
    def __init__(
        self,
        *,
        enabled: bool,
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
        self._enabled = enabled
        self._tick_seconds = max(5, int(tick_seconds))
        self._network_error_retries = max(0, int(network_error_retries))
        self._retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self._max_pages_per_scholar = max(1, int(max_pages_per_scholar))
        self._page_size = max(1, int(page_size))
        self._continuation_queue_enabled = bool(continuation_queue_enabled)
        self._continuation_base_delay_seconds = max(1, int(continuation_base_delay_seconds))
        self._continuation_max_delay_seconds = max(
            self._continuation_base_delay_seconds,
            int(continuation_max_delay_seconds),
        )
        self._continuation_max_attempts = max(1, int(continuation_max_attempts))
        self._queue_batch_size = max(1, int(queue_batch_size))
        self._task: asyncio.Task[None] | None = None
        self._source = LiveScholarSource()

    async def start(self) -> None:
        if not self._enabled:
            logger.info(
                "scheduler.disabled",
                extra={
                    "event": "scheduler.disabled",
                },
            )
            return
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run_loop(), name="scholarr-scheduler")
        logger.info(
            "scheduler.started",
            extra={
                "event": "scheduler.started",
                "tick_seconds": self._tick_seconds,
                "network_error_retries": self._network_error_retries,
                "retry_backoff_seconds": self._retry_backoff_seconds,
                "max_pages_per_scholar": self._max_pages_per_scholar,
                "page_size": self._page_size,
                "continuation_queue_enabled": self._continuation_queue_enabled,
                "continuation_base_delay_seconds": self._continuation_base_delay_seconds,
                "continuation_max_delay_seconds": self._continuation_max_delay_seconds,
                "continuation_max_attempts": self._continuation_max_attempts,
                "queue_batch_size": self._queue_batch_size,
            },
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
        logger.info("scheduler.stopped", extra={"event": "scheduler.stopped"})

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._tick_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "scheduler.tick_failed",
                    extra={
                        "event": "scheduler.tick_failed",
                    },
                )
            await asyncio.sleep(float(self._tick_seconds))

    async def _tick_once(self) -> None:
        if self._continuation_queue_enabled:
            await self._drain_continuation_queue()
        candidates = await self._load_candidates()
        if not candidates:
            return
        now = datetime.now(timezone.utc)
        for candidate in candidates:
            if not await self._is_due(candidate, now=now):
                continue
            await self._run_candidate(candidate)

    async def _load_candidates(self) -> list[_AutoRunCandidate]:
        session_factory = get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(
                    UserSetting.user_id,
                    UserSetting.run_interval_minutes,
                    UserSetting.request_delay_seconds,
                )
                .join(User, User.id == UserSetting.user_id)
                .where(
                    User.is_active.is_(True),
                    UserSetting.auto_run_enabled.is_(True),
                )
                .order_by(UserSetting.user_id.asc())
            )
            rows = result.all()
        return [
            _AutoRunCandidate(
                user_id=int(user_id),
                run_interval_minutes=int(run_interval_minutes),
                request_delay_seconds=int(request_delay_seconds),
            )
            for user_id, run_interval_minutes, request_delay_seconds in rows
        ]

    async def _is_due(self, candidate: _AutoRunCandidate, *, now: datetime) -> bool:
        session_factory = get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(CrawlRun.start_dt)
                .where(
                    CrawlRun.user_id == candidate.user_id,
                )
                .order_by(CrawlRun.start_dt.desc(), CrawlRun.id.desc())
                .limit(1)
            )
            last_run = result.scalar_one_or_none()

        if last_run is None:
            return True

        next_due_dt = last_run + timedelta(
            minutes=candidate.run_interval_minutes
        )
        return now >= next_due_dt

    async def _run_candidate(self, candidate: _AutoRunCandidate) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            ingestion = ScholarIngestionService(source=self._source)
            try:
                run_summary = await ingestion.run_for_user(
                    session,
                    user_id=candidate.user_id,
                    trigger_type=RunTriggerType.SCHEDULED,
                    request_delay_seconds=candidate.request_delay_seconds,
                    network_error_retries=self._network_error_retries,
                    retry_backoff_seconds=self._retry_backoff_seconds,
                    max_pages_per_scholar=self._max_pages_per_scholar,
                    page_size=self._page_size,
                    auto_queue_continuations=self._continuation_queue_enabled,
                    queue_delay_seconds=self._continuation_base_delay_seconds,
                )
            except RunAlreadyInProgressError:
                await session.rollback()
                logger.info(
                    "scheduler.run_skipped_locked",
                    extra={
                        "event": "scheduler.run_skipped_locked",
                        "user_id": candidate.user_id,
                    },
                )
                return
            except Exception:
                await session.rollback()
                logger.exception(
                    "scheduler.run_failed",
                    extra={
                        "event": "scheduler.run_failed",
                        "user_id": candidate.user_id,
                    },
                )
                return

        logger.info(
            "scheduler.run_completed",
            extra={
                "event": "scheduler.run_completed",
                "user_id": candidate.user_id,
                "run_id": run_summary.crawl_run_id,
                "status": run_summary.status.value,
                "scholar_count": run_summary.scholar_count,
                "new_publication_count": run_summary.new_publication_count,
            },
        )

    async def _drain_continuation_queue(self) -> None:
        now = datetime.now(timezone.utc)
        session_factory = get_session_factory()
        async with session_factory() as session:
            jobs = await queue_service.list_due_jobs(
                session,
                now=now,
                limit=self._queue_batch_size,
            )
        for job in jobs:
            await self._run_queue_job(job)

    async def _run_queue_job(self, job: queue_service.ContinuationQueueJob) -> None:
        if job.attempt_count >= self._continuation_max_attempts:
            session_factory = get_session_factory()
            async with session_factory() as session:
                dropped = await queue_service.mark_dropped(
                    session,
                    job_id=job.id,
                    reason="max_attempts_reached",
                )
                await session.commit()
            if dropped is not None:
                logger.warning(
                    "scheduler.queue_item_dropped_max_attempts",
                    extra={
                        "event": "scheduler.queue_item_dropped_max_attempts",
                        "queue_item_id": job.id,
                        "user_id": job.user_id,
                        "scholar_profile_id": job.scholar_profile_id,
                        "attempt_count": job.attempt_count,
                        "max_attempts": self._continuation_max_attempts,
                    },
                )
            return

        session_factory = get_session_factory()
        async with session_factory() as session:
            queue_item = await queue_service.mark_retrying(session, job_id=job.id)
            if queue_item is None:
                await session.commit()
                return
            if queue_item.status == QueueItemStatus.DROPPED.value:
                await session.commit()
                return
            await session.commit()

        async with session_factory() as session:
            scholar_result = await session.execute(
                select(ScholarProfile.id).where(
                    ScholarProfile.user_id == job.user_id,
                    ScholarProfile.id == job.scholar_profile_id,
                    ScholarProfile.is_enabled.is_(True),
                )
            )
            scholar_id = scholar_result.scalar_one_or_none()
            if scholar_id is None:
                dropped = await queue_service.mark_dropped(
                    session,
                    job_id=job.id,
                    reason="scholar_unavailable",
                )
                await session.commit()
                if dropped is not None:
                    logger.info(
                        "scheduler.queue_item_dropped_scholar_unavailable",
                        extra={
                            "event": "scheduler.queue_item_dropped_scholar_unavailable",
                            "queue_item_id": job.id,
                            "user_id": job.user_id,
                            "scholar_profile_id": job.scholar_profile_id,
                        },
                    )
                return

        async with session_factory() as session:
            request_delay_seconds = await self._load_request_delay_for_user(
                session,
                user_id=job.user_id,
            )
            ingestion = ScholarIngestionService(source=self._source)
            try:
                run_summary = await ingestion.run_for_user(
                    session,
                    user_id=job.user_id,
                    trigger_type=RunTriggerType.SCHEDULED,
                    request_delay_seconds=request_delay_seconds,
                    network_error_retries=self._network_error_retries,
                    retry_backoff_seconds=self._retry_backoff_seconds,
                    max_pages_per_scholar=self._max_pages_per_scholar,
                    page_size=self._page_size,
                    scholar_profile_ids={job.scholar_profile_id},
                    start_cstart_by_scholar_id={
                        job.scholar_profile_id: job.resume_cstart,
                    },
                    auto_queue_continuations=self._continuation_queue_enabled,
                    queue_delay_seconds=self._continuation_base_delay_seconds,
                )
            except RunAlreadyInProgressError:
                await session.rollback()
                async with session_factory() as recovery_session:
                    await queue_service.reschedule_job(
                        recovery_session,
                        job_id=job.id,
                        delay_seconds=max(self._tick_seconds, 15),
                        reason="user_run_lock_active",
                        error="run_already_in_progress",
                    )
                    await recovery_session.commit()
                logger.info(
                    "scheduler.queue_item_deferred_lock",
                    extra={
                        "event": "scheduler.queue_item_deferred_lock",
                        "queue_item_id": job.id,
                        "user_id": job.user_id,
                    },
                )
                return
            except Exception as exc:
                await session.rollback()
                async with session_factory() as recovery_session:
                    queue_item = await queue_service.increment_attempt_count(
                        recovery_session,
                        job_id=job.id,
                    )
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
                        logger.warning(
                            "scheduler.queue_item_dropped_after_exception",
                            extra={
                                "event": "scheduler.queue_item_dropped_after_exception",
                                "queue_item_id": job.id,
                                "user_id": job.user_id,
                                "attempt_count": queue_item.attempt_count,
                            },
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
                logger.exception(
                    "scheduler.queue_item_run_failed",
                    extra={
                        "event": "scheduler.queue_item_run_failed",
                        "queue_item_id": job.id,
                        "user_id": job.user_id,
                    },
                )
                return

        async with session_factory() as session:
            # Failed-attempt budget should advance only when continuation execution fails.
            if int(run_summary.failed_count) <= 0:
                queue_item = await queue_service.reset_attempt_count(
                    session,
                    job_id=job.id,
                )
                if queue_item is None:
                    await session.commit()
                    logger.info(
                        "scheduler.queue_item_resolved",
                        extra={
                            "event": "scheduler.queue_item_resolved",
                            "queue_item_id": job.id,
                            "user_id": job.user_id,
                            "run_id": run_summary.crawl_run_id,
                            "status": run_summary.status.value,
                        },
                    )
                    return
                await session.commit()
                logger.info(
                    "scheduler.queue_item_progressed",
                    extra={
                        "event": "scheduler.queue_item_progressed",
                        "queue_item_id": job.id,
                        "user_id": job.user_id,
                        "attempt_count": int(queue_item.attempt_count),
                        "run_id": run_summary.crawl_run_id,
                        "status": run_summary.status.value,
                    },
                )
                return

            queue_item = await queue_service.increment_attempt_count(
                session,
                job_id=job.id,
            )
            if queue_item is None:
                await session.commit()
                logger.info(
                    "scheduler.queue_item_resolved",
                    extra={
                        "event": "scheduler.queue_item_resolved",
                        "queue_item_id": job.id,
                        "user_id": job.user_id,
                        "run_id": run_summary.crawl_run_id,
                        "status": run_summary.status.value,
                    },
                )
                return

            if int(queue_item.attempt_count) >= self._continuation_max_attempts:
                await queue_service.mark_dropped(
                    session,
                    job_id=job.id,
                    reason="max_attempts_after_run",
                )
                await session.commit()
                logger.warning(
                    "scheduler.queue_item_dropped_max_attempts_after_run",
                    extra={
                        "event": "scheduler.queue_item_dropped_max_attempts_after_run",
                        "queue_item_id": job.id,
                        "user_id": job.user_id,
                        "attempt_count": queue_item.attempt_count,
                        "run_id": run_summary.crawl_run_id,
                        "status": run_summary.status.value,
                    },
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
            logger.info(
                "scheduler.queue_item_rescheduled_failed",
                extra={
                    "event": "scheduler.queue_item_rescheduled_failed",
                    "queue_item_id": job.id,
                    "user_id": job.user_id,
                    "attempt_count": queue_item.attempt_count,
                    "delay_seconds": delay_seconds,
                    "run_id": run_summary.crawl_run_id,
                    "status": run_summary.status.value,
                },
            )

    async def _load_request_delay_for_user(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
    ) -> int:
        result = await db_session.execute(
            select(UserSetting.request_delay_seconds).where(UserSetting.user_id == user_id)
        )
        delay = result.scalar_one_or_none()
        if delay is None:
            return 10
        return max(1, int(delay))
