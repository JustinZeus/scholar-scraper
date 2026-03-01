from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CrawlRun,
    RunStatus,
    RunTriggerType,
    ScholarProfile,
)
from app.logging_utils import structured_log
from app.services.ingestion import queue as queue_service
from app.services.ingestion.constants import RUN_LOCK_NAMESPACE
from app.services.ingestion.enrichment import EnrichmentRunner
from app.services.ingestion.pagination import PaginationEngine
from app.services.ingestion.run_completion import (
    complete_run_for_user,
    int_or_default,
    log_run_completed,
    run_execution_summary,
)
from app.services.ingestion.run_enrichment import (
    inline_enrich_and_finalize,
    spawn_background_enrichment_task,
)
from app.services.ingestion.run_guards import (
    load_user_settings_for_run,
    run_preflight_guard,
)
from app.services.ingestion.scholar_processing import run_scholar_iteration
from app.services.ingestion.types import (
    RunAlertSummary,
    RunAlreadyInProgressError,
    RunBlockedBySafetyPolicyError,  # noqa: F401 (re-exported)
    RunFailureSummary,
    RunProgress,
)
from app.services.scholar.source import ScholarSource
from app.services.settings import application as user_settings_service
from app.settings import settings

logger = logging.getLogger(__name__)
ACTIVE_RUN_INDEX_NAME = "uq_crawl_runs_user_active"


def _is_active_run_integrity_error(exc: IntegrityError) -> bool:
    original_error = getattr(exc, "orig", None)
    if ACTIVE_RUN_INDEX_NAME in str(exc):
        return True
    if original_error is None:
        return False
    if ACTIVE_RUN_INDEX_NAME in str(original_error):
        return True
    diagnostics = getattr(original_error, "diag", None)
    if diagnostics is None:
        return False
    return getattr(diagnostics, "constraint_name", None) == ACTIVE_RUN_INDEX_NAME


def _resolve_paging_kwargs(
    *,
    request_delay_seconds: int,
    network_error_retries: int,
    retry_backoff_seconds: float,
    rate_limit_retries: int | None,
    rate_limit_backoff_seconds: float | None,
    max_pages_per_scholar: int,
    page_size: int,
) -> dict[str, Any]:
    return {
        "request_delay_seconds": request_delay_seconds,
        "network_error_retries": network_error_retries,
        "retry_backoff_seconds": retry_backoff_seconds,
        "rate_limit_retries": rate_limit_retries
        if rate_limit_retries is not None
        else settings.ingestion_rate_limit_retries,
        "rate_limit_backoff_seconds": rate_limit_backoff_seconds
        if rate_limit_backoff_seconds is not None
        else settings.ingestion_rate_limit_backoff_seconds,
        "max_pages_per_scholar": max_pages_per_scholar,
        "page_size": page_size,
    }


def _threshold_kwargs(
    *,
    alert_blocked_failure_threshold: int,
    alert_network_failure_threshold: int,
    alert_retry_scheduled_threshold: int,
) -> dict[str, Any]:
    return {
        "alert_blocked_failure_threshold": alert_blocked_failure_threshold,
        "alert_network_failure_threshold": alert_network_failure_threshold,
        "alert_retry_scheduled_threshold": alert_retry_scheduled_threshold,
    }


class ScholarIngestionService:
    def __init__(self, *, source: ScholarSource) -> None:
        self._source = source
        self._pagination = PaginationEngine(source=source)
        self._enrichment = EnrichmentRunner()

    @staticmethod
    def _effective_request_delay_seconds(value: int) -> int:
        policy_minimum = user_settings_service.resolve_request_delay_minimum(
            settings.ingestion_min_request_delay_seconds
        )
        return max(policy_minimum, int_or_default(value, policy_minimum))

    async def _load_target_scholars(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        filtered_scholar_ids: set[int] | None,
    ) -> list[ScholarProfile]:
        scholars_stmt = (
            select(ScholarProfile)
            .where(ScholarProfile.user_id == user_id, ScholarProfile.is_enabled.is_(True))
            .order_by(ScholarProfile.created_at.asc(), ScholarProfile.id.asc())
        )
        if filtered_scholar_ids is not None:
            scholars_stmt = scholars_stmt.where(ScholarProfile.id.in_(filtered_scholar_ids))
        scholars_result = await db_session.execute(scholars_stmt)
        scholars = list(scholars_result.scalars().all())
        if filtered_scholar_ids is not None:
            found_ids = {int(s.id) for s in scholars}
            for sid in filtered_scholar_ids - found_ids:
                await queue_service.clear_job_for_scholar(db_session, user_id=user_id, scholar_profile_id=sid)
        return scholars

    async def _initialize_run_for_user(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        trigger_type: RunTriggerType,
        scholar_profile_ids: set[int] | None,
        start_cstart_by_scholar_id: dict[int, int] | None,
        paging_kwargs: dict[str, Any],
        threshold_kwargs: dict[str, Any],
        idempotency_key: str | None,
    ) -> tuple[Any, CrawlRun, list[ScholarProfile], dict[int, int]]:
        user_settings = await load_user_settings_for_run(
            db_session,
            user_id=user_id,
            trigger_type=trigger_type,
        )
        if not await self._try_acquire_user_lock(db_session, user_id=user_id):
            raise RunAlreadyInProgressError(f"Run already in progress for user_id={user_id}.")
        filtered_scholar_ids = {int(v) for v in scholar_profile_ids} if scholar_profile_ids is not None else None
        start_cstart_map = {int(k): max(0, int(v)) for k, v in (start_cstart_by_scholar_id or {}).items()}
        scholars = await self._load_target_scholars(
            db_session,
            user_id=user_id,
            filtered_scholar_ids=filtered_scholar_ids,
        )
        await run_preflight_guard(
            db_session,
            self._source,
            user_settings=user_settings,
            user_id=user_id,
            scholars=scholars,
        )
        run = await self._start_run_record(
            db_session,
            user_id=user_id,
            trigger_type=trigger_type,
            scholars=scholars,
            filtered=filtered_scholar_ids is not None,
            idempotency_key=idempotency_key,
            paging_kwargs=paging_kwargs,
            threshold_kwargs=threshold_kwargs,
        )
        return user_settings, run, scholars, start_cstart_map

    async def _start_run_record(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        trigger_type: RunTriggerType,
        scholars: list[ScholarProfile],
        filtered: bool,
        idempotency_key: str | None,
        paging_kwargs: dict[str, Any],
        threshold_kwargs: dict[str, Any],
    ) -> CrawlRun:
        structured_log(
            logger,
            "info",
            "ingestion.run_started",
            user_id=user_id,
            trigger_type=trigger_type.value,
            scholar_count=len(scholars),
            is_filtered_run=filtered,
            idempotency_key=idempotency_key,
            **paging_kwargs,
            **threshold_kwargs,
        )
        run = CrawlRun(
            user_id=user_id,
            trigger_type=trigger_type,
            status=RunStatus.RUNNING,
            scholar_count=len(scholars),
            new_pub_count=0,
            idempotency_key=idempotency_key,
            error_log={},
        )
        db_session.add(run)
        try:
            await db_session.flush()
        except IntegrityError as exc:
            if _is_active_run_integrity_error(exc):
                await db_session.rollback()
                raise RunAlreadyInProgressError(f"Run already in progress for user_id={user_id}.") from exc
            raise
        return run

    async def initialize_run(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        trigger_type: RunTriggerType,
        request_delay_seconds: int,
        network_error_retries: int = 1,
        retry_backoff_seconds: float = 1.0,
        rate_limit_retries: int | None = None,
        rate_limit_backoff_seconds: float | None = None,
        max_pages_per_scholar: int = 30,
        page_size: int = 100,
        scholar_profile_ids: set[int] | None = None,
        start_cstart_by_scholar_id: dict[int, int] | None = None,
        idempotency_key: str | None = None,
        alert_blocked_failure_threshold: int = 1,
        alert_network_failure_threshold: int = 2,
        alert_retry_scheduled_threshold: int = 3,
    ) -> tuple[CrawlRun, list[ScholarProfile], dict[int, int]]:
        effective_delay = self._effective_request_delay_seconds(request_delay_seconds)
        if effective_delay != int_or_default(request_delay_seconds, effective_delay):
            structured_log(
                logger,
                "warning",
                "ingestion.delay_coerced",
                user_id=user_id,
                requested_request_delay_seconds=int_or_default(request_delay_seconds, 0),
                effective_request_delay_seconds=effective_delay,
                policy_minimum_request_delay_seconds=user_settings_service.resolve_request_delay_minimum(
                    settings.ingestion_min_request_delay_seconds
                ),
            )
        paging = _resolve_paging_kwargs(
            request_delay_seconds=effective_delay,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
        )
        thresholds = _threshold_kwargs(
            alert_blocked_failure_threshold=alert_blocked_failure_threshold,
            alert_network_failure_threshold=alert_network_failure_threshold,
            alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
        )
        _, run, scholars, start_cstart_map = await self._initialize_run_for_user(
            db_session,
            user_id=user_id,
            trigger_type=trigger_type,
            scholar_profile_ids=scholar_profile_ids,
            start_cstart_by_scholar_id=start_cstart_by_scholar_id,
            idempotency_key=idempotency_key,
            paging_kwargs=paging,
            threshold_kwargs=thresholds,
        )
        return run, scholars, start_cstart_map

    async def execute_run(
        self,
        session_factory: Any,
        *,
        run_id: int,
        user_id: int,
        scholars: list[ScholarProfile],
        start_cstart_map: dict[int, int],
        request_delay_seconds: int,
        network_error_retries: int = 1,
        retry_backoff_seconds: float = 1.0,
        rate_limit_retries: int | None = None,
        rate_limit_backoff_seconds: float | None = None,
        max_pages_per_scholar: int = 30,
        page_size: int = 100,
        auto_queue_continuations: bool = True,
        queue_delay_seconds: int = 60,
        alert_blocked_failure_threshold: int = 1,
        alert_network_failure_threshold: int = 2,
        alert_retry_scheduled_threshold: int = 3,
        idempotency_key: str | None = None,
    ) -> None:
        paging = _resolve_paging_kwargs(
            request_delay_seconds=request_delay_seconds,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
        )
        thresholds = _threshold_kwargs(
            alert_blocked_failure_threshold=alert_blocked_failure_threshold,
            alert_network_failure_threshold=alert_network_failure_threshold,
            alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
        )
        async with session_factory() as db_session:
            try:
                run, user_settings, attached_scholars = await self._prepare_execute_run(
                    db_session, run_id=run_id, user_id=user_id, scholars=scholars
                )
                progress = await run_scholar_iteration(
                    db_session,
                    pagination=self._pagination,
                    run=run,
                    scholars=attached_scholars,
                    user_id=user_id,
                    start_cstart_map=start_cstart_map,
                    auto_queue_continuations=auto_queue_continuations,
                    queue_delay_seconds=queue_delay_seconds,
                    **paging,
                )
                failure_summary, alert_summary = complete_run_for_user(
                    user_settings=user_settings,
                    run=run,
                    scholars=attached_scholars,
                    user_id=user_id,
                    progress=progress,
                    idempotency_key=idempotency_key,
                    **thresholds,
                )
                intended_final_status = run.status
                if intended_final_status not in (RunStatus.CANCELED,):
                    run.status = RunStatus.RESOLVING
                await db_session.commit()
                log_run_completed(
                    run=run,
                    user_id=user_id,
                    scholars=attached_scholars,
                    progress=progress,
                    failure_summary=failure_summary,
                    alert_summary=alert_summary,
                )
                if intended_final_status not in (RunStatus.CANCELED,):
                    spawn_background_enrichment_task(
                        session_factory,
                        self._enrichment,
                        run_id=run.id,
                        intended_final_status=intended_final_status,
                        openalex_api_key=getattr(user_settings, "openalex_api_key", None),
                    )
            except Exception as exc:
                await db_session.rollback()
                structured_log(
                    logger,
                    "exception",
                    "ingestion.background_run_failed",
                    run_id=run_id,
                    user_id=user_id,
                )
                await self._fail_run_in_background(session_factory, run_id, exc)

    async def _prepare_execute_run(
        self,
        db_session: AsyncSession,
        *,
        run_id: int,
        user_id: int,
        scholars: list[ScholarProfile],
    ) -> tuple[CrawlRun, Any, list[ScholarProfile]]:
        run_result = await db_session.execute(select(CrawlRun).where(CrawlRun.id == run_id))
        run = run_result.scalar_one()
        user_settings = await user_settings_service.get_or_create_settings(db_session, user_id=user_id)
        scholar_ids = [s.id for s in scholars]
        scholars_result = await db_session.execute(
            select(ScholarProfile)
            .where(ScholarProfile.id.in_(scholar_ids))
            .order_by(ScholarProfile.created_at.asc(), ScholarProfile.id.asc())
        )
        return run, user_settings, list(scholars_result.scalars().all())

    async def _fail_run_in_background(self, session_factory: Any, run_id: int, exc: Exception) -> None:
        try:
            async with session_factory() as cleanup_session:
                run_to_fail = await cleanup_session.get(CrawlRun, run_id)
                if run_to_fail:
                    run_to_fail.status = RunStatus.FAILED
                    run_to_fail.end_dt = datetime.now(UTC)
                    run_to_fail.error_log["terminal_exception"] = str(exc)
                    await cleanup_session.commit()
        except Exception:
            structured_log(
                logger,
                "exception",
                "ingestion.fail_run_cleanup_failed",
                run_id=run_id,
            )

    async def run_for_user(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        trigger_type: RunTriggerType,
        request_delay_seconds: int,
        network_error_retries: int = 1,
        retry_backoff_seconds: float = 1.0,
        rate_limit_retries: int | None = None,
        rate_limit_backoff_seconds: float | None = None,
        max_pages_per_scholar: int = 30,
        page_size: int = 100,
        scholar_profile_ids: set[int] | None = None,
        start_cstart_by_scholar_id: dict[int, int] | None = None,
        auto_queue_continuations: bool = True,
        queue_delay_seconds: int = 60,
        idempotency_key: str | None = None,
        alert_blocked_failure_threshold: int = 1,
        alert_network_failure_threshold: int = 2,
        alert_retry_scheduled_threshold: int = 3,
    ):
        run, scholars, start_cstart_map = await self.initialize_run(
            db_session,
            user_id=user_id,
            trigger_type=trigger_type,
            request_delay_seconds=request_delay_seconds,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
            scholar_profile_ids=scholar_profile_ids,
            start_cstart_by_scholar_id=start_cstart_by_scholar_id,
            idempotency_key=idempotency_key,
            alert_blocked_failure_threshold=alert_blocked_failure_threshold,
            alert_network_failure_threshold=alert_network_failure_threshold,
            alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
        )
        paging = _resolve_paging_kwargs(
            request_delay_seconds=self._effective_request_delay_seconds(request_delay_seconds),
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
        )
        thresholds = _threshold_kwargs(
            alert_blocked_failure_threshold=alert_blocked_failure_threshold,
            alert_network_failure_threshold=alert_network_failure_threshold,
            alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
        )
        progress, failure_summary, alert_summary, intended_final_status = await self._run_iteration_and_complete(
            db_session,
            run=run,
            scholars=scholars,
            user_id=user_id,
            start_cstart_map=start_cstart_map,
            paging=paging,
            thresholds=thresholds,
            auto_queue_continuations=auto_queue_continuations,
            queue_delay_seconds=queue_delay_seconds,
            idempotency_key=idempotency_key,
        )
        user_settings = await user_settings_service.get_or_create_settings(db_session, user_id=user_id)
        await inline_enrich_and_finalize(
            db_session,
            self._enrichment,
            run=run,
            user_settings=user_settings,
            intended_final_status=intended_final_status,
        )
        log_run_completed(
            run=run,
            user_id=user_id,
            scholars=scholars,
            progress=progress,
            failure_summary=failure_summary,
            alert_summary=alert_summary,
        )
        return run_execution_summary(run=run, scholars=scholars, progress=progress)

    async def _run_iteration_and_complete(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholars: list[ScholarProfile],
        user_id: int,
        start_cstart_map: dict[int, int],
        paging: dict[str, Any],
        thresholds: dict[str, Any],
        auto_queue_continuations: bool,
        queue_delay_seconds: int,
        idempotency_key: str | None,
    ) -> tuple[RunProgress, RunFailureSummary, RunAlertSummary, RunStatus]:
        progress = await run_scholar_iteration(
            db_session,
            pagination=self._pagination,
            run=run,
            scholars=scholars,
            user_id=user_id,
            start_cstart_map=start_cstart_map,
            auto_queue_continuations=auto_queue_continuations,
            queue_delay_seconds=queue_delay_seconds,
            **paging,
        )
        user_settings = await user_settings_service.get_or_create_settings(db_session, user_id=user_id)
        failure_summary, alert_summary = complete_run_for_user(
            user_settings=user_settings,
            run=run,
            scholars=scholars,
            user_id=user_id,
            progress=progress,
            idempotency_key=idempotency_key,
            **thresholds,
        )
        intended_final_status = run.status
        if intended_final_status not in (RunStatus.CANCELED,):
            run.status = RunStatus.RESOLVING
        await db_session.commit()
        return progress, failure_summary, alert_summary, intended_final_status

    async def _try_acquire_user_lock(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
    ) -> bool:
        result = await db_session.execute(
            text("SELECT pg_try_advisory_xact_lock(:namespace, :user_key)"),
            {"namespace": RUN_LOCK_NAMESPACE, "user_key": int(user_id)},
        )
        return bool(result.scalar_one())
