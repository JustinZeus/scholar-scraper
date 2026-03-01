from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db.models import (
    CrawlRun,
    RunTriggerType,
    User,
    UserSetting,
)
from app.db.session import get_session_factory
from app.logging_utils import structured_log
from app.services.ingestion.application import (
    RunAlreadyInProgressError,
    RunBlockedBySafetyPolicyError,
    ScholarIngestionService,
)
from app.services.ingestion.queue_runner import QueueJobRunner, effective_request_delay_seconds
from app.services.scholar.source import LiveScholarSource
from app.services.settings import application as user_settings_service
from app.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _AutoRunCandidate:
    user_id: int
    run_interval_minutes: int
    request_delay_seconds: int
    cooldown_until: datetime | None
    cooldown_reason: str | None


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
        self._queue_runner = QueueJobRunner(
            tick_seconds=self._tick_seconds,
            network_error_retries=self._network_error_retries,
            retry_backoff_seconds=self._retry_backoff_seconds,
            max_pages_per_scholar=self._max_pages_per_scholar,
            page_size=self._page_size,
            continuation_queue_enabled=self._continuation_queue_enabled,
            continuation_base_delay_seconds=self._continuation_base_delay_seconds,
            continuation_max_delay_seconds=self._continuation_max_delay_seconds,
            continuation_max_attempts=self._continuation_max_attempts,
            queue_batch_size=self._queue_batch_size,
        )

    async def start(self) -> None:
        if not self._enabled:
            structured_log(logger, "info", "scheduler.disabled")
            return
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run_loop(), name="scholarr-scheduler")
        structured_log(
            logger,
            "info",
            "scheduler.started",
            tick_seconds=self._tick_seconds,
            network_error_retries=self._network_error_retries,
            retry_backoff_seconds=self._retry_backoff_seconds,
            max_pages_per_scholar=self._max_pages_per_scholar,
            page_size=self._page_size,
            continuation_queue_enabled=self._continuation_queue_enabled,
            continuation_base_delay_seconds=self._continuation_base_delay_seconds,
            continuation_max_delay_seconds=self._continuation_max_delay_seconds,
            continuation_max_attempts=self._continuation_max_attempts,
            queue_batch_size=self._queue_batch_size,
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
        structured_log(logger, "info", "scheduler.stopped")

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._tick_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                structured_log(
                    logger,
                    "exception",
                    "scheduler.tick_failed",
                )
            await asyncio.sleep(float(self._tick_seconds))

    async def _tick_once(self) -> None:
        if self._continuation_queue_enabled:
            await self._queue_runner.drain_continuation_queue()

        await self._drain_pdf_queue()

        candidates = await self._load_candidates()
        if not candidates:
            return
        now = datetime.now(UTC)
        for candidate in candidates:
            if not await self._is_due(candidate, now=now):
                continue
            await self._run_candidate(candidate)

    async def _load_candidate_rows(self) -> list[Any]:
        session_factory = get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                select(
                    UserSetting.user_id,
                    UserSetting.run_interval_minutes,
                    UserSetting.request_delay_seconds,
                    UserSetting.scrape_cooldown_until,
                    UserSetting.scrape_cooldown_reason,
                )
                .join(User, User.id == UserSetting.user_id)
                .where(User.is_active.is_(True), UserSetting.auto_run_enabled.is_(True))
                .order_by(UserSetting.user_id.asc())
            )
            return list(result.all())

    @staticmethod
    def _candidate_from_row(row: Any, *, now_utc: datetime) -> _AutoRunCandidate | None:
        user_id, run_interval_minutes, request_delay_seconds, cooldown_until, cooldown_reason = row
        if cooldown_until is not None and cooldown_until.tzinfo is None:
            cooldown_until = cooldown_until.replace(tzinfo=UTC)
        if cooldown_until is not None and cooldown_until > now_utc:
            structured_log(
                logger,
                "info",
                "scheduler.run_skipped_safety_cooldown_precheck",
                user_id=int(user_id),
                reason=cooldown_reason,
                cooldown_until=cooldown_until,
                cooldown_remaining_seconds=int((cooldown_until - now_utc).total_seconds()),
            )
            return None
        return _AutoRunCandidate(
            user_id=int(user_id),
            run_interval_minutes=int(run_interval_minutes),
            request_delay_seconds=effective_request_delay_seconds(
                request_delay_seconds,
                floor=user_settings_service.resolve_request_delay_minimum(settings.ingestion_min_request_delay_seconds),
            ),
            cooldown_until=cooldown_until,
            cooldown_reason=(str(cooldown_reason).strip() if cooldown_reason else None),
        )

    async def _load_candidates(self) -> list[_AutoRunCandidate]:
        if not settings.ingestion_automation_allowed:
            return []
        rows = await self._load_candidate_rows()
        now_utc = datetime.now(UTC)
        candidates: list[_AutoRunCandidate] = []
        for row in rows:
            candidate = self._candidate_from_row(row, now_utc=now_utc)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

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

        next_due_dt = last_run + timedelta(minutes=candidate.run_interval_minutes)
        return now >= next_due_dt

    async def _run_candidate_ingestion(
        self,
        *,
        candidate: _AutoRunCandidate,
    ):
        session_factory = get_session_factory()
        async with session_factory() as session:
            ingestion = ScholarIngestionService(source=self._source)
            try:
                return await ingestion.run_for_user(
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
                    alert_blocked_failure_threshold=settings.ingestion_alert_blocked_failure_threshold,
                    alert_network_failure_threshold=settings.ingestion_alert_network_failure_threshold,
                    alert_retry_scheduled_threshold=settings.ingestion_alert_retry_scheduled_threshold,
                )
            except RunAlreadyInProgressError:
                await session.rollback()
                structured_log(logger, "info", "scheduler.run_skipped_locked", user_id=candidate.user_id)
                return None
            except RunBlockedBySafetyPolicyError as exc:
                await session.rollback()
                structured_log(
                    logger,
                    "info",
                    "scheduler.run_skipped_safety_cooldown",
                    user_id=candidate.user_id,
                    reason=exc.safety_state.get("cooldown_reason"),
                    cooldown_until=exc.safety_state.get("cooldown_until"),
                    cooldown_remaining_seconds=exc.safety_state.get("cooldown_remaining_seconds"),
                )
                return None
            except Exception:
                await session.rollback()
                structured_log(
                    logger,
                    "exception",
                    "scheduler.run_failed",
                    user_id=candidate.user_id,
                )
                return None

    async def _run_candidate(self, candidate: _AutoRunCandidate) -> None:
        run_summary = await self._run_candidate_ingestion(candidate=candidate)
        if run_summary is None:
            return
        structured_log(
            logger,
            "info",
            "scheduler.run_completed",
            user_id=candidate.user_id,
            run_id=run_summary.crawl_run_id,
            status=run_summary.status.value,
            scholar_count=run_summary.scholar_count,
            new_publication_count=run_summary.new_publication_count,
        )

    async def _drain_pdf_queue(self) -> None:
        from app.services.publications.pdf_queue import drain_ready_jobs

        session_factory = get_session_factory()
        async with session_factory() as session:
            try:
                processed = await drain_ready_jobs(
                    session,
                    limit=settings.scheduler_pdf_queue_batch_size,
                    max_attempts=settings.pdf_auto_retry_max_attempts,
                )
                if processed > 0:
                    structured_log(
                        logger,
                        "info",
                        "scheduler.pdf_queue_drain_completed",
                        processed_count=processed,
                    )
            except Exception:
                structured_log(
                    logger,
                    "exception",
                    "scheduler.pdf_queue_drain_failed",
                )
