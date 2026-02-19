from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CrawlRun,
    Publication,
    RunStatus,
    RunTriggerType,
    ScholarProfile,
    ScholarPublication,
)
from app.services import continuation_queue as queue_service
from app.services import run_safety as run_safety_service
from app.services import user_settings as user_settings_service
from app.services.scholar_parser import (
    ParseState,
    ParsedProfilePage,
    PublicationCandidate,
    parse_profile_page,
)
from app.services.scholar_source import FetchResult, ScholarSource
from app.settings import settings

TITLE_ALNUM_RE = re.compile(r"[^a-z0-9]+")
WORD_RE = re.compile(r"[a-z0-9]+")
HTML_TAG_RE = re.compile(r"<[^>]+>", re.S)
SPACE_RE = re.compile(r"\s+")
FAILED_STATES = {
    ParseState.BLOCKED_OR_CAPTCHA.value,
    ParseState.LAYOUT_CHANGED.value,
    ParseState.NETWORK_ERROR.value,
    "ingestion_error",
}
FAILURE_BUCKET_BLOCKED = "blocked_or_captcha"
FAILURE_BUCKET_NETWORK = "network_error"
FAILURE_BUCKET_LAYOUT = "layout_changed"
FAILURE_BUCKET_INGESTION = "ingestion_error"
FAILURE_BUCKET_OTHER = "other_failure"
RUN_LOCK_NAMESPACE = 8217
RESUMABLE_PARTIAL_REASONS = {
    "max_pages_reached",
    "pagination_cursor_stalled",
}
RESUMABLE_PARTIAL_REASON_PREFIXES = ("page_state_network_error",)
INITIAL_PAGE_FINGERPRINT_MAX_PUBLICATIONS = 30
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunExecutionSummary:
    crawl_run_id: int
    status: RunStatus
    scholar_count: int
    succeeded_count: int
    failed_count: int
    partial_count: int
    new_publication_count: int


@dataclass(frozen=True)
class PagedParseResult:
    fetch_result: FetchResult
    parsed_page: ParsedProfilePage
    first_page_fetch_result: FetchResult
    first_page_parsed_page: ParsedProfilePage
    first_page_fingerprint_sha256: str | None
    publications: list[PublicationCandidate]
    attempt_log: list[dict[str, Any]]
    page_logs: list[dict[str, Any]]
    pages_fetched: int
    pages_attempted: int
    has_more_remaining: bool
    pagination_truncated_reason: str | None
    continuation_cstart: int | None
    skipped_no_change: bool


@dataclass
class RunProgress:
    succeeded_count: int = 0
    failed_count: int = 0
    partial_count: int = 0
    scholar_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ScholarProcessingOutcome:
    result_entry: dict[str, Any]
    succeeded_count_delta: int
    failed_count_delta: int
    partial_count_delta: int
    discovered_publication_count: int


@dataclass(frozen=True)
class RunFailureSummary:
    failed_state_counts: dict[str, int]
    failed_reason_counts: dict[str, int]
    scrape_failure_counts: dict[str, int]
    retries_scheduled_count: int
    scholars_with_retries_count: int
    retry_exhausted_count: int


@dataclass(frozen=True)
class RunAlertSummary:
    blocked_failure_count: int
    network_failure_count: int
    blocked_failure_threshold: int
    network_failure_threshold: int
    retry_scheduled_threshold: int
    alert_flags: dict[str, bool]


@dataclass
class PagedLoopState:
    fetch_result: FetchResult
    parsed_page: ParsedProfilePage
    attempt_log: list[dict[str, Any]]
    page_logs: list[dict[str, Any]]
    publications: list[PublicationCandidate]
    pages_fetched: int
    pages_attempted: int
    current_cstart: int
    next_cstart: int
    has_more_remaining: bool = False
    pagination_truncated_reason: str | None = None
    continuation_cstart: int | None = None


class RunAlreadyInProgressError(RuntimeError):
    """Raised when a run lock for a user is already held by another process."""


class RunBlockedBySafetyPolicyError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        safety_state: dict[str, Any],
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.safety_state = safety_state


def _int_or_default(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _classify_failure_bucket(*, state: str, state_reason: str) -> str:
    reason = state_reason.strip().lower()
    normalized_state = state.strip().lower()

    if normalized_state == ParseState.BLOCKED_OR_CAPTCHA.value or reason.startswith("blocked_"):
        return FAILURE_BUCKET_BLOCKED
    if normalized_state == ParseState.NETWORK_ERROR.value or reason.startswith("network_"):
        return FAILURE_BUCKET_NETWORK
    if normalized_state == ParseState.LAYOUT_CHANGED.value:
        return FAILURE_BUCKET_LAYOUT
    if normalized_state == "ingestion_error":
        return FAILURE_BUCKET_INGESTION
    return FAILURE_BUCKET_OTHER


class ScholarIngestionService:
    def __init__(self, *, source: ScholarSource) -> None:
        self._source = source

    async def _load_user_settings_for_run(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        trigger_type: RunTriggerType,
    ):
        user_settings = await user_settings_service.get_or_create_settings(
            db_session,
            user_id=user_id,
        )
        await self._enforce_safety_gate(
            db_session,
            user_settings=user_settings,
            user_id=user_id,
            trigger_type=trigger_type,
        )
        return user_settings

    async def _enforce_safety_gate(
        self,
        db_session: AsyncSession,
        *,
        user_settings,
        user_id: int,
        trigger_type: RunTriggerType,
    ) -> None:
        now_utc = datetime.now(timezone.utc)
        previous = run_safety_service.get_safety_event_context(user_settings, now_utc=now_utc)
        if run_safety_service.clear_expired_cooldown(user_settings, now_utc=now_utc):
            await db_session.commit()
            await db_session.refresh(user_settings)
            logger.info(
                "ingestion.safety_cooldown_cleared",
                extra={
                    "event": "ingestion.safety_cooldown_cleared",
                    "user_id": user_id,
                    "reason": previous.get("cooldown_reason"),
                    "cooldown_until": previous.get("cooldown_until"),
                    "metric_name": "ingestion_safety_cooldown_cleared_total",
                    "metric_value": 1,
                },
            )
            now_utc = datetime.now(timezone.utc)
        if run_safety_service.is_cooldown_active(user_settings, now_utc=now_utc):
            await self._raise_safety_blocked_start(
                db_session,
                user_settings=user_settings,
                user_id=user_id,
                trigger_type=trigger_type,
                now_utc=now_utc,
            )

    async def _raise_safety_blocked_start(
        self,
        db_session: AsyncSession,
        *,
        user_settings,
        user_id: int,
        trigger_type: RunTriggerType,
        now_utc: datetime,
    ) -> None:
        safety_state = run_safety_service.register_cooldown_blocked_start(
            user_settings,
            now_utc=now_utc,
        )
        await db_session.commit()
        logger.warning(
            "ingestion.safety_policy_blocked_run_start",
            extra={
                "event": "ingestion.safety_policy_blocked_run_start",
                "user_id": user_id,
                "trigger_type": trigger_type.value,
                "reason": safety_state.get("cooldown_reason"),
                "cooldown_until": safety_state.get("cooldown_until"),
                "cooldown_remaining_seconds": safety_state.get("cooldown_remaining_seconds"),
                "blocked_start_count": ((safety_state.get("counters") or {}).get("blocked_start_count")),
                "metric_name": "ingestion_safety_run_start_blocked_total",
                "metric_value": 1,
            },
        )
        raise RunBlockedBySafetyPolicyError(
            code="scrape_cooldown_active",
            message="Scrape safety cooldown is active; run start is temporarily blocked.",
            safety_state=safety_state,
        )

    @staticmethod
    def _normalize_run_targets(
        *,
        scholar_profile_ids: set[int] | None,
        start_cstart_by_scholar_id: dict[int, int] | None,
    ) -> tuple[set[int] | None, dict[int, int]]:
        filtered_scholar_ids = (
            {int(value) for value in scholar_profile_ids}
            if scholar_profile_ids is not None
            else None
        )
        start_cstart_map = {
            int(key): max(0, int(value))
            for key, value in (start_cstart_by_scholar_id or {}).items()
        }
        return filtered_scholar_ids, start_cstart_map

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
        await self._clear_missing_filtered_jobs(
            db_session,
            user_id=user_id,
            filtered_scholar_ids=filtered_scholar_ids,
            scholars=scholars,
        )
        return scholars

    async def _clear_missing_filtered_jobs(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        filtered_scholar_ids: set[int] | None,
        scholars: list[ScholarProfile],
    ) -> None:
        if filtered_scholar_ids is None:
            return
        found_ids = {int(scholar.id) for scholar in scholars}
        missing_ids = filtered_scholar_ids - found_ids
        for scholar_profile_id in missing_ids:
            await queue_service.clear_job_for_scholar(
                db_session,
                user_id=user_id,
                scholar_profile_id=scholar_profile_id,
            )

    @staticmethod
    def _create_running_run(
        *,
        user_id: int,
        trigger_type: RunTriggerType,
        scholar_count: int,
        idempotency_key: str | None,
    ) -> CrawlRun:
        return CrawlRun(
            user_id=user_id,
            trigger_type=trigger_type,
            status=RunStatus.RUNNING,
            scholar_count=scholar_count,
            new_pub_count=0,
            idempotency_key=idempotency_key,
            error_log={},
        )

    @staticmethod
    def _log_run_started(
        *,
        user_id: int,
        trigger_type: RunTriggerType,
        scholar_count: int,
        filtered: bool,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
        idempotency_key: str | None,
        alert_blocked_failure_threshold: int,
        alert_network_failure_threshold: int,
        alert_retry_scheduled_threshold: int,
    ) -> None:
        logger.info(
            "ingestion.run_started",
            extra={
                "event": "ingestion.run_started",
                "user_id": user_id,
                "trigger_type": trigger_type.value,
                "scholar_count": scholar_count,
                "is_filtered_run": filtered,
                "request_delay_seconds": request_delay_seconds,
                "network_error_retries": network_error_retries,
                "retry_backoff_seconds": retry_backoff_seconds,
                "max_pages_per_scholar": max_pages_per_scholar,
                "page_size": page_size,
                "idempotency_key": idempotency_key,
                "alert_blocked_failure_threshold": alert_blocked_failure_threshold,
                "alert_network_failure_threshold": alert_network_failure_threshold,
                "alert_retry_scheduled_threshold": alert_retry_scheduled_threshold,
            },
        )

    @staticmethod
    async def _wait_between_scholars(*, index: int, request_delay_seconds: int) -> None:
        if index <= 0 or request_delay_seconds <= 0:
            return
        await asyncio.sleep(float(request_delay_seconds))

    @staticmethod
    def _assert_valid_paged_parse_result(
        *,
        scholar_id: str,
        paged_parse_result: PagedParseResult,
    ) -> None:
        parsed_page = paged_parse_result.parsed_page
        if parsed_page.state in {ParseState.OK, ParseState.NO_RESULTS}:
            if any(code.startswith("layout_") for code in parsed_page.warnings):
                raise RuntimeError(f"Layout warning marked as terminal for scholar_id={scholar_id}.")
        for publication in paged_parse_result.publications:
            if not publication.title.strip():
                raise RuntimeError(f"Malformed publication title for scholar_id={scholar_id}.")
            if publication.citation_count is not None and int(publication.citation_count) < 0:
                raise RuntimeError(f"Negative citation count for scholar_id={scholar_id}.")

    @staticmethod
    def _apply_first_page_profile_metadata(
        *,
        scholar: ScholarProfile,
        paged_parse_result: PagedParseResult,
        run_dt: datetime,
    ) -> None:
        first_page = paged_parse_result.first_page_parsed_page
        if first_page.profile_name and not (scholar.display_name or "").strip():
            scholar.display_name = first_page.profile_name
        if first_page.profile_image_url:
            scholar.profile_image_url = first_page.profile_image_url
        if paged_parse_result.first_page_fingerprint_sha256:
            scholar.last_initial_page_fingerprint_sha256 = paged_parse_result.first_page_fingerprint_sha256
        scholar.last_initial_page_checked_at = run_dt

    @staticmethod
    def _log_scholar_parsed(
        *,
        user_id: int,
        run_id: int,
        scholar: ScholarProfile,
        paged_parse_result: PagedParseResult,
    ) -> None:
        parsed_page = paged_parse_result.parsed_page
        logger.info(
            "ingestion.scholar_parsed",
            extra={
                "event": "ingestion.scholar_parsed",
                "user_id": user_id,
                "crawl_run_id": run_id,
                "scholar_profile_id": scholar.id,
                "scholar_id": scholar.scholar_id,
                "state": parsed_page.state.value,
                "publication_count": len(paged_parse_result.publications),
                "has_show_more_button": parsed_page.has_show_more_button,
                "pages_fetched": paged_parse_result.pages_fetched,
                "pages_attempted": paged_parse_result.pages_attempted,
                "has_more_remaining": paged_parse_result.has_more_remaining,
                "pagination_truncated_reason": paged_parse_result.pagination_truncated_reason,
                "warning_count": len(parsed_page.warnings),
                "skipped_no_change": paged_parse_result.skipped_no_change,
            },
        )

    @staticmethod
    def _build_result_entry(
        *,
        scholar: ScholarProfile,
        start_cstart: int,
        paged_parse_result: PagedParseResult,
    ) -> dict[str, Any]:
        parsed_page = paged_parse_result.parsed_page
        return {
            "scholar_profile_id": scholar.id,
            "scholar_id": scholar.scholar_id,
            "state": parsed_page.state.value,
            "state_reason": parsed_page.state_reason,
            "outcome": "failed",
            "attempt_count": len(paged_parse_result.attempt_log),
            "publication_count": len(paged_parse_result.publications),
            "start_cstart": start_cstart,
            "articles_range": parsed_page.articles_range,
            "warnings": parsed_page.warnings,
            "has_show_more_button": parsed_page.has_show_more_button,
            "pages_fetched": paged_parse_result.pages_fetched,
            "pages_attempted": paged_parse_result.pages_attempted,
            "has_more_remaining": paged_parse_result.has_more_remaining,
            "pagination_truncated_reason": paged_parse_result.pagination_truncated_reason,
            "continuation_cstart": paged_parse_result.continuation_cstart,
            "skipped_no_change": paged_parse_result.skipped_no_change,
            "initial_page_fingerprint_sha256": paged_parse_result.first_page_fingerprint_sha256,
        }

    def _skipped_no_change_outcome(
        self,
        *,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
    ) -> ScholarProcessingOutcome:
        first_page = paged_parse_result.first_page_parsed_page
        scholar.last_run_status = RunStatus.SUCCESS
        scholar.last_run_dt = run_dt
        result_entry["state"] = first_page.state.value
        result_entry["state_reason"] = "no_change_initial_page_signature"
        result_entry["outcome"] = "success"
        result_entry["publication_count"] = 0
        result_entry["warnings"] = first_page.warnings
        result_entry["debug"] = {
            "state_reason": "no_change_initial_page_signature",
            "first_page_fingerprint_sha256": paged_parse_result.first_page_fingerprint_sha256,
            "attempt_log": paged_parse_result.attempt_log,
            "page_logs": paged_parse_result.page_logs,
        }
        return ScholarProcessingOutcome(
            result_entry=result_entry,
            succeeded_count_delta=1,
            failed_count_delta=0,
            partial_count_delta=0,
            discovered_publication_count=0,
        )

    async def _upsert_publications_outcome(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
    ) -> ScholarProcessingOutcome:
        parsed_page = paged_parse_result.parsed_page
        publications = paged_parse_result.publications
        had_page_failure = parsed_page.state not in {ParseState.OK, ParseState.NO_RESULTS}
        has_partial_set = len(publications) > 0 and had_page_failure
        if (not had_page_failure) or has_partial_set:
            return await self._upsert_success_or_exception(
                db_session,
                run=run,
                scholar=scholar,
                run_dt=run_dt,
                paged_parse_result=paged_parse_result,
                result_entry=result_entry,
                has_partial_publication_set=has_partial_set,
            )
        return self._parse_failure_outcome(
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
        )

    async def _upsert_success_or_exception(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
        has_partial_publication_set: bool,
    ) -> ScholarProcessingOutcome:
        try:
            return await self._upsert_success(
                db_session,
                run=run,
                scholar=scholar,
                run_dt=run_dt,
                paged_parse_result=paged_parse_result,
                result_entry=result_entry,
                has_partial_publication_set=has_partial_publication_set,
            )
        except Exception as exc:
            return self._upsert_exception_outcome(
                run=run,
                scholar=scholar,
                run_dt=run_dt,
                paged_parse_result=paged_parse_result,
                result_entry=result_entry,
                exc=exc,
            )

    async def _upsert_success(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
        has_partial_publication_set: bool,
    ) -> ScholarProcessingOutcome:
        discovered_count = await self._upsert_profile_publications(
            db_session,
            run=run,
            scholar=scholar,
            publications=paged_parse_result.publications,
        )
        is_partial = (
            paged_parse_result.has_more_remaining
            or paged_parse_result.pagination_truncated_reason is not None
            or has_partial_publication_set
        )
        scholar.last_run_status = RunStatus.PARTIAL_FAILURE if is_partial else RunStatus.SUCCESS
        scholar.last_run_dt = run_dt
        result_entry["outcome"] = "partial" if is_partial else "success"
        if is_partial:
            result_entry["debug"] = self._build_failure_debug_context(
                fetch_result=paged_parse_result.fetch_result,
                parsed_page=paged_parse_result.parsed_page,
                attempt_log=paged_parse_result.attempt_log,
                page_logs=paged_parse_result.page_logs,
            )
        return ScholarProcessingOutcome(
            result_entry=result_entry,
            succeeded_count_delta=1,
            failed_count_delta=0,
            partial_count_delta=1 if is_partial else 0,
            discovered_publication_count=discovered_count,
        )

    def _upsert_exception_outcome(
        self,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
        exc: Exception,
    ) -> ScholarProcessingOutcome:
        scholar.last_run_status = RunStatus.FAILED
        scholar.last_run_dt = run_dt
        result_entry["state"] = "ingestion_error"
        result_entry["state_reason"] = "publication_upsert_exception"
        result_entry["outcome"] = "failed"
        result_entry["error"] = str(exc)
        result_entry["debug"] = self._build_failure_debug_context(
            fetch_result=paged_parse_result.fetch_result,
            parsed_page=paged_parse_result.parsed_page,
            attempt_log=paged_parse_result.attempt_log,
            page_logs=paged_parse_result.page_logs,
            exception=exc,
        )
        logger.exception(
            "ingestion.scholar_failed",
            extra={
                "event": "ingestion.scholar_failed",
                "crawl_run_id": run.id,
                "scholar_profile_id": scholar.id,
                "scholar_id": scholar.scholar_id,
            },
        )
        return ScholarProcessingOutcome(result_entry, 0, 1, 0, 0)

    def _parse_failure_outcome(
        self,
        *,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
    ) -> ScholarProcessingOutcome:
        scholar.last_run_status = RunStatus.FAILED
        scholar.last_run_dt = run_dt
        result_entry["debug"] = self._build_failure_debug_context(
            fetch_result=paged_parse_result.fetch_result,
            parsed_page=paged_parse_result.parsed_page,
            attempt_log=paged_parse_result.attempt_log,
            page_logs=paged_parse_result.page_logs,
        )
        logger.warning(
            "ingestion.scholar_parse_failed",
            extra={
                "event": "ingestion.scholar_parse_failed",
                "scholar_profile_id": scholar.id,
                "scholar_id": scholar.scholar_id,
                "state": paged_parse_result.parsed_page.state.value,
                "state_reason": paged_parse_result.parsed_page.state_reason,
                "status_code": paged_parse_result.fetch_result.status_code,
            },
        )
        return ScholarProcessingOutcome(result_entry, 0, 1, 0, 0)

    async def _sync_continuation_queue(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        scholar: ScholarProfile,
        run: CrawlRun,
        start_cstart: int,
        result_entry: dict[str, Any],
        paged_parse_result: PagedParseResult,
        auto_queue_continuations: bool,
        queue_delay_seconds: int,
    ) -> None:
        queue_reason, queue_cstart = self._resolve_continuation_queue_target(
            outcome=str(result_entry.get("outcome", "")),
            state=str(result_entry.get("state", "")),
            pagination_truncated_reason=paged_parse_result.pagination_truncated_reason,
            continuation_cstart=paged_parse_result.continuation_cstart,
            fallback_cstart=start_cstart,
        )
        if auto_queue_continuations and queue_reason is not None:
            await queue_service.upsert_job(
                db_session,
                user_id=user_id,
                scholar_profile_id=scholar.id,
                resume_cstart=queue_cstart,
                reason=queue_reason,
                run_id=run.id,
                delay_seconds=queue_delay_seconds,
            )
            result_entry["continuation_enqueued"] = True
            result_entry["continuation_reason"] = queue_reason
            result_entry["continuation_cstart"] = queue_cstart
            return
        if await queue_service.clear_job_for_scholar(db_session, user_id=user_id, scholar_profile_id=scholar.id):
            result_entry["continuation_cleared"] = True

    async def _process_scholar(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        user_id: int,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
        start_cstart: int,
        auto_queue_continuations: bool,
        queue_delay_seconds: int,
    ) -> ScholarProcessingOutcome:
        try:
            return await self._process_scholar_inner(
                db_session,
                run=run,
                scholar=scholar,
                user_id=user_id,
                request_delay_seconds=request_delay_seconds,
                network_error_retries=network_error_retries,
                retry_backoff_seconds=retry_backoff_seconds,
                max_pages_per_scholar=max_pages_per_scholar,
                page_size=page_size,
                start_cstart=start_cstart,
                auto_queue_continuations=auto_queue_continuations,
                queue_delay_seconds=queue_delay_seconds,
            )
        except Exception as exc:
            return self._unexpected_scholar_exception_outcome(
                run=run,
                scholar=scholar,
                start_cstart=start_cstart,
                exc=exc,
            )

    async def _process_scholar_inner(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        user_id: int,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
        start_cstart: int,
        auto_queue_continuations: bool,
        queue_delay_seconds: int,
    ) -> ScholarProcessingOutcome:
        run_dt, paged_parse_result, result_entry = await self._fetch_and_prepare_scholar_result(
            run=run,
            scholar=scholar,
            user_id=user_id,
            start_cstart=start_cstart,
            request_delay_seconds=request_delay_seconds,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
        )
        outcome = await self._resolve_scholar_outcome(
            db_session,
            run=run,
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
        )
        await self._sync_continuation_queue(
            db_session,
            user_id=user_id,
            scholar=scholar,
            run=run,
            start_cstart=start_cstart,
            result_entry=outcome.result_entry,
            paged_parse_result=paged_parse_result,
            auto_queue_continuations=auto_queue_continuations,
            queue_delay_seconds=queue_delay_seconds,
        )
        return outcome

    async def _fetch_and_prepare_scholar_result(
        self,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        user_id: int,
        start_cstart: int,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
    ) -> tuple[datetime, PagedParseResult, dict[str, Any]]:
        run_dt = datetime.now(timezone.utc)
        paged_parse_result = await self._fetch_and_parse_all_pages_with_retry(
            scholar_id=scholar.scholar_id,
            start_cstart=start_cstart,
            request_delay_seconds=request_delay_seconds,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            max_pages=max_pages_per_scholar,
            page_size=page_size,
            previous_initial_page_fingerprint_sha256=scholar.last_initial_page_fingerprint_sha256,
        )
        self._assert_valid_paged_parse_result(scholar_id=scholar.scholar_id, paged_parse_result=paged_parse_result)
        self._apply_first_page_profile_metadata(scholar=scholar, paged_parse_result=paged_parse_result, run_dt=run_dt)
        self._log_scholar_parsed(user_id=user_id, run_id=run.id, scholar=scholar, paged_parse_result=paged_parse_result)
        result_entry = self._build_result_entry(
            scholar=scholar,
            start_cstart=start_cstart,
            paged_parse_result=paged_parse_result,
        )
        return run_dt, paged_parse_result, result_entry

    async def _resolve_scholar_outcome(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        run_dt: datetime,
        paged_parse_result: PagedParseResult,
        result_entry: dict[str, Any],
    ) -> ScholarProcessingOutcome:
        if paged_parse_result.skipped_no_change:
            return self._skipped_no_change_outcome(
                scholar=scholar,
                run_dt=run_dt,
                paged_parse_result=paged_parse_result,
                result_entry=result_entry,
            )
        return await self._upsert_publications_outcome(
            db_session,
            run=run,
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
        )

    @staticmethod
    def _apply_outcome_to_progress(
        *,
        progress: RunProgress,
        run: CrawlRun,
        outcome: ScholarProcessingOutcome,
    ) -> None:
        progress.succeeded_count += outcome.succeeded_count_delta
        progress.failed_count += outcome.failed_count_delta
        progress.partial_count += outcome.partial_count_delta
        run.new_pub_count = int(run.new_pub_count or 0) + outcome.discovered_publication_count
        progress.scholar_results.append(outcome.result_entry)

    def _unexpected_scholar_exception_outcome(
        self,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        start_cstart: int,
        exc: Exception,
    ) -> ScholarProcessingOutcome:
        scholar.last_run_status = RunStatus.FAILED
        scholar.last_run_dt = datetime.now(timezone.utc)
        logger.exception(
            "ingestion.scholar_unexpected_failure",
            extra={
                "event": "ingestion.scholar_unexpected_failure",
                "crawl_run_id": run.id,
                "scholar_profile_id": scholar.id,
                "scholar_id": scholar.scholar_id,
            },
        )
        return ScholarProcessingOutcome(
            result_entry={
                "scholar_profile_id": scholar.id,
                "scholar_id": scholar.scholar_id,
                "state": "ingestion_error",
                "state_reason": "scholar_processing_exception",
                "outcome": "failed",
                "attempt_count": 0,
                "publication_count": 0,
                "start_cstart": start_cstart,
                "warnings": [],
                "error": str(exc),
                "debug": {"exception_type": type(exc).__name__, "exception_message": str(exc)},
            },
            succeeded_count_delta=0,
            failed_count_delta=1,
            partial_count_delta=0,
            discovered_publication_count=0,
        )

    @staticmethod
    def _summarize_failures(
        *,
        scholar_results: list[dict[str, Any]],
    ) -> RunFailureSummary:
        failed_state_counts: dict[str, int] = {}
        failed_reason_counts: dict[str, int] = {}
        scrape_failure_counts: dict[str, int] = {}
        retries_scheduled_count = 0
        scholars_with_retries_count = 0
        retry_exhausted_count = 0
        for entry in scholar_results:
            retries_for_entry = max(0, _int_or_default(entry.get("attempt_count"), 0) - 1)
            if retries_for_entry > 0:
                retries_scheduled_count += retries_for_entry
                scholars_with_retries_count += 1
            if str(entry.get("outcome", "")) != "failed":
                continue
            state = str(entry.get("state", "")).strip()
            if state not in FAILED_STATES:
                continue
            failed_state_counts[state] = failed_state_counts.get(state, 0) + 1
            reason = str(entry.get("state_reason", "")).strip()
            if reason:
                failed_reason_counts[reason] = failed_reason_counts.get(reason, 0) + 1
            bucket = _classify_failure_bucket(state=state, state_reason=reason)
            scrape_failure_counts[bucket] = scrape_failure_counts.get(bucket, 0) + 1
            if state == ParseState.NETWORK_ERROR.value and retries_for_entry > 0:
                retry_exhausted_count += 1
        return RunFailureSummary(
            failed_state_counts=failed_state_counts,
            failed_reason_counts=failed_reason_counts,
            scrape_failure_counts=scrape_failure_counts,
            retries_scheduled_count=retries_scheduled_count,
            scholars_with_retries_count=scholars_with_retries_count,
            retry_exhausted_count=retry_exhausted_count,
        )

    @staticmethod
    def _build_alert_summary(
        *,
        failure_summary: RunFailureSummary,
        alert_blocked_failure_threshold: int,
        alert_network_failure_threshold: int,
        alert_retry_scheduled_threshold: int,
    ) -> RunAlertSummary:
        blocked_failure_count = int(failure_summary.scrape_failure_counts.get(FAILURE_BUCKET_BLOCKED, 0))
        network_failure_count = int(failure_summary.scrape_failure_counts.get(FAILURE_BUCKET_NETWORK, 0))
        blocked_threshold = max(1, int(alert_blocked_failure_threshold))
        network_threshold = max(1, int(alert_network_failure_threshold))
        retry_threshold = max(1, int(alert_retry_scheduled_threshold))
        alert_flags = {
            "blocked_failure_threshold_exceeded": blocked_failure_count >= blocked_threshold,
            "network_failure_threshold_exceeded": network_failure_count >= network_threshold,
            "retry_scheduled_threshold_exceeded": failure_summary.retries_scheduled_count >= retry_threshold,
        }
        return RunAlertSummary(
            blocked_failure_count=blocked_failure_count,
            network_failure_count=network_failure_count,
            blocked_failure_threshold=blocked_threshold,
            network_failure_threshold=network_threshold,
            retry_scheduled_threshold=retry_threshold,
            alert_flags=alert_flags,
        )

    @staticmethod
    def _log_alert_thresholds(
        *,
        user_id: int,
        run_id: int,
        failure_summary: RunFailureSummary,
        alert_summary: RunAlertSummary,
    ) -> None:
        if alert_summary.alert_flags["blocked_failure_threshold_exceeded"]:
            logger.warning(
                "ingestion.alert_blocked_failure_threshold_exceeded",
                extra={
                    "event": "ingestion.alert_blocked_failure_threshold_exceeded",
                    "user_id": user_id,
                    "crawl_run_id": run_id,
                    "blocked_failure_count": alert_summary.blocked_failure_count,
                    "threshold": alert_summary.blocked_failure_threshold,
                    "metric_name": "ingestion_blocked_failure_threshold_exceeded_total",
                    "metric_value": 1,
                },
            )
        if alert_summary.alert_flags["network_failure_threshold_exceeded"]:
            logger.warning(
                "ingestion.alert_network_failure_threshold_exceeded",
                extra={
                    "event": "ingestion.alert_network_failure_threshold_exceeded",
                    "user_id": user_id,
                    "crawl_run_id": run_id,
                    "network_failure_count": alert_summary.network_failure_count,
                    "threshold": alert_summary.network_failure_threshold,
                    "metric_name": "ingestion_network_failure_threshold_exceeded_total",
                    "metric_value": 1,
                },
            )
        if alert_summary.alert_flags["retry_scheduled_threshold_exceeded"]:
            logger.warning(
                "ingestion.alert_retry_scheduled_threshold_exceeded",
                extra={
                    "event": "ingestion.alert_retry_scheduled_threshold_exceeded",
                    "user_id": user_id,
                    "crawl_run_id": run_id,
                    "retries_scheduled_count": failure_summary.retries_scheduled_count,
                    "threshold": alert_summary.retry_scheduled_threshold,
                    "metric_name": "ingestion_retry_scheduled_threshold_exceeded_total",
                    "metric_value": 1,
                },
            )

    @staticmethod
    def _apply_safety_outcome(
        *,
        user_settings,
        run: CrawlRun,
        user_id: int,
        alert_summary: RunAlertSummary,
    ) -> None:
        pre_apply_state = run_safety_service.get_safety_event_context(
            user_settings,
            now_utc=datetime.now(timezone.utc),
        )
        safety_state, cooldown_trigger_reason = run_safety_service.apply_run_safety_outcome(
            user_settings,
            run_id=int(run.id),
            blocked_failure_count=alert_summary.blocked_failure_count,
            network_failure_count=alert_summary.network_failure_count,
            blocked_failure_threshold=alert_summary.blocked_failure_threshold,
            network_failure_threshold=alert_summary.network_failure_threshold,
            blocked_cooldown_seconds=settings.ingestion_safety_cooldown_blocked_seconds,
            network_cooldown_seconds=settings.ingestion_safety_cooldown_network_seconds,
            now_utc=datetime.now(timezone.utc),
        )
        ScholarIngestionService._log_safety_transition(
            user_id=user_id,
            run_id=int(run.id),
            alert_summary=alert_summary,
            pre_apply_state=pre_apply_state,
            safety_state=safety_state,
            cooldown_trigger_reason=cooldown_trigger_reason,
        )

    @staticmethod
    def _log_safety_transition(
        *,
        user_id: int,
        run_id: int,
        alert_summary: RunAlertSummary,
        pre_apply_state: dict[str, Any],
        safety_state: dict[str, Any],
        cooldown_trigger_reason: str | None,
    ) -> None:
        if cooldown_trigger_reason is not None:
            logger.warning(
                "ingestion.safety_cooldown_entered",
                extra={
                    "event": "ingestion.safety_cooldown_entered",
                    "user_id": user_id,
                    "crawl_run_id": run_id,
                    "reason": cooldown_trigger_reason,
                    "blocked_failure_count": alert_summary.blocked_failure_count,
                    "network_failure_count": alert_summary.network_failure_count,
                    "blocked_failure_threshold": alert_summary.blocked_failure_threshold,
                    "network_failure_threshold": alert_summary.network_failure_threshold,
                    "cooldown_until": safety_state.get("cooldown_until"),
                    "cooldown_remaining_seconds": safety_state.get("cooldown_remaining_seconds"),
                    "safety_counters": safety_state.get("counters", {}),
                    "metric_name": "ingestion_safety_cooldown_entered_total",
                    "metric_value": 1,
                },
            )
        elif pre_apply_state.get("cooldown_active") and not safety_state.get("cooldown_active"):
            logger.info(
                "ingestion.safety_cooldown_cleared",
                extra={
                    "event": "ingestion.safety_cooldown_cleared",
                    "user_id": user_id,
                    "crawl_run_id": run_id,
                    "reason": pre_apply_state.get("cooldown_reason"),
                    "cooldown_until": pre_apply_state.get("cooldown_until"),
                    "metric_name": "ingestion_safety_cooldown_cleared_total",
                    "metric_value": 1,
                },
            )

    def _finalize_run_record(
        self,
        *,
        run: CrawlRun,
        scholars: list[ScholarProfile],
        progress: RunProgress,
        failure_summary: RunFailureSummary,
        alert_summary: RunAlertSummary,
        idempotency_key: str | None,
    ) -> None:
        run.end_dt = datetime.now(timezone.utc)
        run.status = self._resolve_run_status(
            scholar_count=len(scholars),
            succeeded_count=progress.succeeded_count,
            failed_count=progress.failed_count,
            partial_count=progress.partial_count,
        )
        run.error_log = {
            "scholar_results": progress.scholar_results,
            "summary": {
                "succeeded_count": progress.succeeded_count,
                "failed_count": progress.failed_count,
                "partial_count": progress.partial_count,
                "failed_state_counts": failure_summary.failed_state_counts,
                "failed_reason_counts": failure_summary.failed_reason_counts,
                "scrape_failure_counts": failure_summary.scrape_failure_counts,
                "retry_counts": {
                    "retries_scheduled_count": failure_summary.retries_scheduled_count,
                    "scholars_with_retries_count": failure_summary.scholars_with_retries_count,
                    "retry_exhausted_count": failure_summary.retry_exhausted_count,
                },
                "alert_thresholds": {
                    "blocked_failure_threshold": alert_summary.blocked_failure_threshold,
                    "network_failure_threshold": alert_summary.network_failure_threshold,
                    "retry_scheduled_threshold": alert_summary.retry_scheduled_threshold,
                },
                "alert_flags": alert_summary.alert_flags,
            },
            "meta": {"idempotency_key": idempotency_key} if idempotency_key else {},
        }

    @staticmethod
    def _log_run_completed(
        *,
        user_id: int,
        run: CrawlRun,
        scholars: list[ScholarProfile],
        progress: RunProgress,
        alert_summary: RunAlertSummary,
        failure_summary: RunFailureSummary,
    ) -> None:
        logger.info(
            "ingestion.run_completed",
            extra={
                "event": "ingestion.run_completed",
                "user_id": user_id,
                "crawl_run_id": run.id,
                "status": run.status.value,
                "scholar_count": len(scholars),
                "succeeded_count": progress.succeeded_count,
                "failed_count": progress.failed_count,
                "partial_count": progress.partial_count,
                "new_publication_count": run.new_pub_count,
                "blocked_failure_count": alert_summary.blocked_failure_count,
                "network_failure_count": alert_summary.network_failure_count,
                "retries_scheduled_count": failure_summary.retries_scheduled_count,
                "alert_flags": alert_summary.alert_flags,
            },
        )

    @staticmethod
    def _paging_kwargs(
        *,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
    ) -> dict[str, Any]:
        return {
            "request_delay_seconds": request_delay_seconds,
            "network_error_retries": network_error_retries,
            "retry_backoff_seconds": retry_backoff_seconds,
            "max_pages_per_scholar": max_pages_per_scholar,
            "page_size": page_size,
        }

    @staticmethod
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

    @staticmethod
    def _run_execution_summary(
        *,
        run: CrawlRun,
        scholars: list[ScholarProfile],
        progress: RunProgress,
    ) -> RunExecutionSummary:
        return RunExecutionSummary(
            crawl_run_id=run.id,
            status=run.status,
            scholar_count=len(scholars),
            succeeded_count=progress.succeeded_count,
            failed_count=progress.failed_count,
            partial_count=progress.partial_count,
            new_publication_count=run.new_pub_count,
        )

    async def _initialize_run_for_user(self, db_session: AsyncSession, *, user_id: int, trigger_type: RunTriggerType, scholar_profile_ids: set[int] | None, start_cstart_by_scholar_id: dict[int, int] | None, request_delay_seconds: int, network_error_retries: int, retry_backoff_seconds: float, max_pages_per_scholar: int, page_size: int, idempotency_key: str | None, alert_blocked_failure_threshold: int, alert_network_failure_threshold: int, alert_retry_scheduled_threshold: int) -> tuple[Any, CrawlRun, list[ScholarProfile], dict[int, int]]:
        user_settings = await self._load_user_settings_for_run(
            db_session,
            user_id=user_id,
            trigger_type=trigger_type,
        )
        if not await self._try_acquire_user_lock(db_session, user_id=user_id):
            raise RunAlreadyInProgressError(f"Run already in progress for user_id={user_id}.")
        filtered_scholar_ids, start_cstart_map = self._normalize_run_targets(
            scholar_profile_ids=scholar_profile_ids,
            start_cstart_by_scholar_id=start_cstart_by_scholar_id,
        )
        scholars = await self._load_target_scholars(
            db_session,
            user_id=user_id,
            filtered_scholar_ids=filtered_scholar_ids,
        )
        run = await self._start_run_record_for_targets(
            db_session,
            user_id=user_id,
            trigger_type=trigger_type,
            scholars=scholars,
            filtered=filtered_scholar_ids is not None,
            request_delay_seconds=request_delay_seconds,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
            idempotency_key=idempotency_key,
            alert_blocked_failure_threshold=alert_blocked_failure_threshold,
            alert_network_failure_threshold=alert_network_failure_threshold,
            alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
        )
        return user_settings, run, scholars, start_cstart_map

    async def _start_run_record_for_targets(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        trigger_type: RunTriggerType,
        scholars: list[ScholarProfile],
        filtered: bool,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
        idempotency_key: str | None,
        alert_blocked_failure_threshold: int,
        alert_network_failure_threshold: int,
        alert_retry_scheduled_threshold: int,
    ) -> CrawlRun:
        self._log_run_started(
            user_id=user_id,
            trigger_type=trigger_type,
            scholar_count=len(scholars),
            filtered=filtered,
            request_delay_seconds=request_delay_seconds,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
            idempotency_key=idempotency_key,
            alert_blocked_failure_threshold=alert_blocked_failure_threshold,
            alert_network_failure_threshold=alert_network_failure_threshold,
            alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
        )
        run = self._create_running_run(
            user_id=user_id,
            trigger_type=trigger_type,
            scholar_count=len(scholars),
            idempotency_key=idempotency_key,
        )
        db_session.add(run)
        await db_session.flush()
        return run

    async def _run_scholar_iteration(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholars: list[ScholarProfile],
        user_id: int,
        start_cstart_map: dict[int, int],
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        max_pages_per_scholar: int,
        page_size: int,
        auto_queue_continuations: bool,
        queue_delay_seconds: int,
    ) -> RunProgress:
        progress = RunProgress()
        for index, scholar in enumerate(scholars):
            await self._wait_between_scholars(index=index, request_delay_seconds=request_delay_seconds)
            start_cstart = int(start_cstart_map.get(int(scholar.id), 0))
            outcome = await self._process_scholar(
                db_session,
                run=run,
                scholar=scholar,
                user_id=user_id,
                request_delay_seconds=request_delay_seconds,
                network_error_retries=network_error_retries,
                retry_backoff_seconds=retry_backoff_seconds,
                max_pages_per_scholar=max_pages_per_scholar,
                page_size=page_size,
                start_cstart=start_cstart,
                auto_queue_continuations=auto_queue_continuations,
                queue_delay_seconds=queue_delay_seconds,
            )
            self._apply_outcome_to_progress(progress=progress, run=run, outcome=outcome)
        return progress

    def _complete_run_for_user(
        self,
        *,
        user_settings: Any,
        run: CrawlRun,
        scholars: list[ScholarProfile],
        user_id: int,
        progress: RunProgress,
        idempotency_key: str | None,
        alert_blocked_failure_threshold: int,
        alert_network_failure_threshold: int,
        alert_retry_scheduled_threshold: int,
    ) -> tuple[RunFailureSummary, RunAlertSummary]:
        failure_summary = self._summarize_failures(scholar_results=progress.scholar_results)
        alert_summary = self._build_alert_summary(
            failure_summary=failure_summary,
            alert_blocked_failure_threshold=alert_blocked_failure_threshold,
            alert_network_failure_threshold=alert_network_failure_threshold,
            alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
        )
        self._log_alert_thresholds(
            user_id=user_id,
            run_id=int(run.id),
            failure_summary=failure_summary,
            alert_summary=alert_summary,
        )
        self._apply_safety_outcome(user_settings=user_settings, run=run, user_id=user_id, alert_summary=alert_summary)
        self._finalize_run_record(
            run=run,
            scholars=scholars,
            progress=progress,
            failure_summary=failure_summary,
            alert_summary=alert_summary,
            idempotency_key=idempotency_key,
        )
        return failure_summary, alert_summary

    async def run_for_user(self, db_session: AsyncSession, *, user_id: int, trigger_type: RunTriggerType, request_delay_seconds: int, network_error_retries: int = 1, retry_backoff_seconds: float = 1.0, max_pages_per_scholar: int = 30, page_size: int = 100, scholar_profile_ids: set[int] | None = None, start_cstart_by_scholar_id: dict[int, int] | None = None, auto_queue_continuations: bool = True, queue_delay_seconds: int = 60, idempotency_key: str | None = None, alert_blocked_failure_threshold: int = 1, alert_network_failure_threshold: int = 2, alert_retry_scheduled_threshold: int = 3) -> RunExecutionSummary:
        paging_kwargs = self._paging_kwargs(request_delay_seconds=request_delay_seconds, network_error_retries=network_error_retries, retry_backoff_seconds=retry_backoff_seconds, max_pages_per_scholar=max_pages_per_scholar, page_size=page_size)
        threshold_kwargs = self._threshold_kwargs(alert_blocked_failure_threshold=alert_blocked_failure_threshold, alert_network_failure_threshold=alert_network_failure_threshold, alert_retry_scheduled_threshold=alert_retry_scheduled_threshold)
        user_settings, run, scholars, start_cstart_map = await self._initialize_run_for_user(
            db_session,
            user_id=user_id,
            trigger_type=trigger_type,
            scholar_profile_ids=scholar_profile_ids,
            start_cstart_by_scholar_id=start_cstart_by_scholar_id,
            idempotency_key=idempotency_key,
            **paging_kwargs,
            **threshold_kwargs,
        )
        progress = await self._run_scholar_iteration(
            db_session,
            run=run,
            scholars=scholars,
            user_id=user_id,
            start_cstart_map=start_cstart_map,
            auto_queue_continuations=auto_queue_continuations,
            queue_delay_seconds=queue_delay_seconds,
            **paging_kwargs,
        )
        failure_summary, alert_summary = self._complete_run_for_user(
            user_settings=user_settings,
            run=run,
            scholars=scholars,
            user_id=user_id,
            progress=progress,
            idempotency_key=idempotency_key,
            **threshold_kwargs,
        )
        await db_session.commit()
        self._log_run_completed(user_id=user_id, run=run, scholars=scholars, progress=progress, alert_summary=alert_summary, failure_summary=failure_summary)
        return self._run_execution_summary(run=run, scholars=scholars, progress=progress)

    async def _fetch_profile_page(
        self,
        *,
        scholar_id: str,
        cstart: int,
        page_size: int,
    ) -> FetchResult:
        try:
            page_fetcher = getattr(self._source, "fetch_profile_page_html", None)
            if callable(page_fetcher):
                return await page_fetcher(
                    scholar_id,
                    cstart=cstart,
                    pagesize=page_size,
                )
            if cstart <= 0:
                return await self._source.fetch_profile_html(scholar_id)
            return FetchResult(
                requested_url=(
                    "https://scholar.google.com/citations"
                    f"?hl=en&user={scholar_id}&cstart={cstart}&pagesize={page_size}"
                ),
                status_code=None,
                final_url=None,
                body="",
                error="source_does_not_support_pagination",
            )
        except Exception as exc:
            logger.exception(
                "ingestion.fetch_unexpected_error",
                extra={
                    "event": "ingestion.fetch_unexpected_error",
                    "scholar_id": scholar_id,
                    "cstart": cstart,
                    "page_size": page_size,
                },
            )
            return FetchResult(
                requested_url=(
                    "https://scholar.google.com/citations"
                    f"?hl=en&user={scholar_id}&cstart={cstart}&pagesize={page_size}"
                ),
                status_code=None,
                final_url=None,
                body="",
                error=str(exc),
            )

    @staticmethod
    def _attempt_log_entry(
        *,
        attempt: int,
        cstart: int,
        fetch_result: FetchResult,
        parsed_page: ParsedProfilePage,
    ) -> dict[str, Any]:
        return {
            "attempt": attempt,
            "cstart": cstart,
            "state": parsed_page.state.value,
            "state_reason": parsed_page.state_reason,
            "status_code": fetch_result.status_code,
            "fetch_error": fetch_result.error,
        }

    @staticmethod
    def _should_retry_network_page(
        *,
        parsed_page: ParsedProfilePage,
        attempt_index: int,
        max_attempts: int,
    ) -> bool:
        return parsed_page.state == ParseState.NETWORK_ERROR and attempt_index < max_attempts - 1

    @staticmethod
    async def _sleep_retry_backoff(
        *,
        scholar_id: str,
        cstart: int,
        attempt_index: int,
        backoff: float,
        state_reason: str,
    ) -> None:
        sleep_seconds = backoff * (2**attempt_index)
        logger.warning(
            "ingestion.scholar_retry_scheduled",
            extra={
                "event": "ingestion.scholar_retry_scheduled",
                "scholar_id": scholar_id,
                "cstart": cstart,
                "attempt": attempt_index + 1,
                "next_attempt": attempt_index + 2,
                "sleep_seconds": sleep_seconds,
                "state_reason": state_reason,
            },
        )
        if sleep_seconds > 0:
            await asyncio.sleep(sleep_seconds)

    async def _fetch_and_parse_page_with_retry(
        self,
        *,
        scholar_id: str,
        cstart: int,
        page_size: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
    ) -> tuple[FetchResult, ParsedProfilePage, list[dict[str, Any]]]:
        max_attempts = max(1, int(network_error_retries) + 1)
        backoff = max(float(retry_backoff_seconds), 0.0)
        attempt_log: list[dict[str, Any]] = []
        fetch_result: FetchResult | None = None
        parsed_page: ParsedProfilePage | None = None

        for attempt_index in range(max_attempts):
            fetch_result = await self._fetch_profile_page(
                scholar_id=scholar_id,
                cstart=cstart,
                page_size=page_size,
            )
            parsed_page = parse_profile_page(fetch_result)
            attempt_log.append(
                self._attempt_log_entry(
                    attempt=attempt_index + 1,
                    cstart=cstart,
                    fetch_result=fetch_result,
                    parsed_page=parsed_page,
                )
            )
            if not self._should_retry_network_page(
                parsed_page=parsed_page,
                attempt_index=attempt_index,
                max_attempts=max_attempts,
            ):
                break
            await self._sleep_retry_backoff(
                scholar_id=scholar_id,
                cstart=cstart,
                attempt_index=attempt_index,
                backoff=backoff,
                state_reason=parsed_page.state_reason,
            )

        if fetch_result is None or parsed_page is None:
            raise RuntimeError("Fetch-and-parse retry loop produced no result.")
        return fetch_result, parsed_page, attempt_log

    @staticmethod
    def _page_log_entry(
        *,
        page_number: int,
        cstart: int,
        fetch_result: FetchResult,
        parsed_page: ParsedProfilePage,
        attempt_count: int,
    ) -> dict[str, Any]:
        return {
            "page": page_number,
            "cstart": cstart,
            "state": parsed_page.state.value,
            "state_reason": parsed_page.state_reason,
            "status_code": fetch_result.status_code,
            "publication_count": len(parsed_page.publications),
            "articles_range": parsed_page.articles_range,
            "has_show_more_button": parsed_page.has_show_more_button,
            "warning_codes": parsed_page.warnings,
            "attempt_count": attempt_count,
        }

    @staticmethod
    def _should_skip_no_change(
        *,
        start_cstart: int,
        first_page_fingerprint_sha256: str | None,
        previous_initial_page_fingerprint_sha256: str | None,
        parsed_page: ParsedProfilePage,
    ) -> bool:
        return (
            start_cstart <= 0
            and first_page_fingerprint_sha256 is not None
            and previous_initial_page_fingerprint_sha256 is not None
            and first_page_fingerprint_sha256 == previous_initial_page_fingerprint_sha256
            and parsed_page.state in {ParseState.OK, ParseState.NO_RESULTS}
        )

    @staticmethod
    def _skip_no_change_result(
        *,
        fetch_result: FetchResult,
        parsed_page: ParsedProfilePage,
        first_page_fingerprint_sha256: str | None,
        attempt_log: list[dict[str, Any]],
        page_logs: list[dict[str, Any]],
    ) -> PagedParseResult:
        return PagedParseResult(
            fetch_result=fetch_result,
            parsed_page=parsed_page,
            first_page_fetch_result=fetch_result,
            first_page_parsed_page=parsed_page,
            first_page_fingerprint_sha256=first_page_fingerprint_sha256,
            publications=[],
            attempt_log=attempt_log,
            page_logs=page_logs,
            pages_fetched=1,
            pages_attempted=1,
            has_more_remaining=False,
            pagination_truncated_reason=None,
            continuation_cstart=None,
            skipped_no_change=True,
        )

    @staticmethod
    def _initial_failure_result(
        *,
        fetch_result: FetchResult,
        parsed_page: ParsedProfilePage,
        first_page_fingerprint_sha256: str | None,
        start_cstart: int,
        attempt_log: list[dict[str, Any]],
        page_logs: list[dict[str, Any]],
    ) -> PagedParseResult:
        continuation_cstart = start_cstart if parsed_page.state == ParseState.NETWORK_ERROR else None
        return PagedParseResult(
            fetch_result=fetch_result,
            parsed_page=parsed_page,
            first_page_fetch_result=fetch_result,
            first_page_parsed_page=parsed_page,
            first_page_fingerprint_sha256=first_page_fingerprint_sha256,
            publications=[],
            attempt_log=attempt_log,
            page_logs=page_logs,
            pages_fetched=0,
            pages_attempted=1,
            has_more_remaining=False,
            pagination_truncated_reason=None,
            continuation_cstart=continuation_cstart,
            skipped_no_change=False,
        )

    @staticmethod
    def _build_loop_state(
        *,
        start_cstart: int,
        fetch_result: FetchResult,
        parsed_page: ParsedProfilePage,
        attempt_log: list[dict[str, Any]],
        page_logs: list[dict[str, Any]],
    ) -> PagedLoopState:
        next_cstart = _next_cstart_value(
            articles_range=parsed_page.articles_range,
            fallback=start_cstart + len(parsed_page.publications),
        )
        return PagedLoopState(
            fetch_result=fetch_result,
            parsed_page=parsed_page,
            attempt_log=attempt_log,
            page_logs=page_logs,
            publications=list(parsed_page.publications),
            pages_fetched=1,
            pages_attempted=1,
            current_cstart=start_cstart,
            next_cstart=next_cstart,
        )

    @staticmethod
    def _set_truncated_state(
        *,
        state: PagedLoopState,
        reason: str,
        continuation_cstart: int,
    ) -> None:
        state.has_more_remaining = True
        state.pagination_truncated_reason = reason
        state.continuation_cstart = continuation_cstart

    def _should_stop_pagination(self, *, state: PagedLoopState, bounded_max_pages: int) -> bool:
        if state.pages_fetched >= bounded_max_pages:
            self._set_truncated_state(
                state=state,
                reason="max_pages_reached",
                continuation_cstart=(
                    state.next_cstart if state.next_cstart > state.current_cstart else state.current_cstart
                ),
            )
            return True
        if state.next_cstart <= state.current_cstart:
            self._set_truncated_state(
                state=state,
                reason="pagination_cursor_stalled",
                continuation_cstart=state.current_cstart,
            )
            return True
        return False

    async def _fetch_next_page(
        self,
        *,
        scholar_id: str,
        state: PagedLoopState,
        request_delay_seconds: int,
        bounded_page_size: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
    ) -> tuple[FetchResult, ParsedProfilePage, list[dict[str, Any]]]:
        if request_delay_seconds > 0:
            await asyncio.sleep(float(request_delay_seconds))
        state.current_cstart = state.next_cstart
        return await self._fetch_and_parse_page_with_retry(
            scholar_id=scholar_id,
            cstart=state.current_cstart,
            page_size=bounded_page_size,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )

    @staticmethod
    def _record_next_page(
        *,
        state: PagedLoopState,
        fetch_result: FetchResult,
        parsed_page: ParsedProfilePage,
        page_attempt_log: list[dict[str, Any]],
    ) -> None:
        state.pages_attempted += 1
        state.attempt_log.extend(page_attempt_log)
        state.page_logs.append(
            ScholarIngestionService._page_log_entry(
                page_number=state.pages_attempted,
                cstart=state.current_cstart,
                fetch_result=fetch_result,
                parsed_page=parsed_page,
                attempt_count=len(page_attempt_log),
            )
        )
        state.fetch_result = fetch_result
        state.parsed_page = parsed_page

    @staticmethod
    def _handle_page_state_transition(*, state: PagedLoopState) -> bool:
        if state.parsed_page.state not in {ParseState.OK, ParseState.NO_RESULTS}:
            ScholarIngestionService._set_truncated_state(
                state=state,
                reason=f"page_state_{state.parsed_page.state.value}",
                continuation_cstart=state.current_cstart,
            )
            return True
        if state.parsed_page.state == ParseState.NO_RESULTS and len(state.parsed_page.publications) == 0:
            state.pages_fetched += 1
            return True
        state.pages_fetched += 1
        state.publications.extend(state.parsed_page.publications)
        state.next_cstart = _next_cstart_value(
            articles_range=state.parsed_page.articles_range,
            fallback=state.current_cstart + len(state.parsed_page.publications),
        )
        return False

    async def _fetch_initial_page_context(
        self,
        *,
        scholar_id: str,
        start_cstart: int,
        bounded_page_size: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
    ) -> tuple[FetchResult, ParsedProfilePage, str | None, list[dict[str, Any]], list[dict[str, Any]]]:
        fetch_result, parsed_page, first_attempt_log = await self._fetch_and_parse_page_with_retry(
            scholar_id=scholar_id,
            cstart=start_cstart,
            page_size=bounded_page_size,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        first_page_fingerprint_sha256 = build_initial_page_fingerprint(parsed_page)
        attempt_log = list(first_attempt_log)
        page_logs = [
            self._page_log_entry(
                page_number=1,
                cstart=start_cstart,
                fetch_result=fetch_result,
                parsed_page=parsed_page,
                attempt_count=len(first_attempt_log),
            )
        ]
        return fetch_result, parsed_page, first_page_fingerprint_sha256, attempt_log, page_logs

    async def _paginate_loop(
        self,
        *,
        scholar_id: str,
        state: PagedLoopState,
        bounded_max_pages: int,
        request_delay_seconds: int,
        bounded_page_size: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
    ) -> None:
        while state.parsed_page.has_show_more_button:
            if self._should_stop_pagination(state=state, bounded_max_pages=bounded_max_pages):
                return
            next_fetch_result, next_parsed_page, next_attempt_log = await self._fetch_next_page(
                scholar_id=scholar_id,
                state=state,
                request_delay_seconds=request_delay_seconds,
                bounded_page_size=bounded_page_size,
                network_error_retries=network_error_retries,
                retry_backoff_seconds=retry_backoff_seconds,
            )
            self._record_next_page(
                state=state,
                fetch_result=next_fetch_result,
                parsed_page=next_parsed_page,
                page_attempt_log=next_attempt_log,
            )
            if self._handle_page_state_transition(state=state):
                return

    @staticmethod
    def _result_from_pagination_state(
        *,
        state: PagedLoopState,
        first_page_fetch_result: FetchResult,
        first_page_parsed_page: ParsedProfilePage,
        first_page_fingerprint_sha256: str | None,
    ) -> PagedParseResult:
        return PagedParseResult(
            fetch_result=state.fetch_result,
            parsed_page=state.parsed_page,
            first_page_fetch_result=first_page_fetch_result,
            first_page_parsed_page=first_page_parsed_page,
            first_page_fingerprint_sha256=first_page_fingerprint_sha256,
            publications=_dedupe_publication_candidates(state.publications),
            attempt_log=state.attempt_log,
            page_logs=state.page_logs,
            pages_fetched=state.pages_fetched,
            pages_attempted=state.pages_attempted,
            has_more_remaining=state.has_more_remaining,
            pagination_truncated_reason=state.pagination_truncated_reason,
            continuation_cstart=state.continuation_cstart,
            skipped_no_change=False,
        )

    def _short_circuit_initial_page(
        self,
        *,
        start_cstart: int,
        previous_initial_page_fingerprint_sha256: str | None,
        fetch_result: FetchResult,
        parsed_page: ParsedProfilePage,
        first_page_fingerprint_sha256: str | None,
        attempt_log: list[dict[str, Any]],
        page_logs: list[dict[str, Any]],
    ) -> PagedParseResult | None:
        if self._should_skip_no_change(
            start_cstart=start_cstart,
            first_page_fingerprint_sha256=first_page_fingerprint_sha256,
            previous_initial_page_fingerprint_sha256=previous_initial_page_fingerprint_sha256,
            parsed_page=parsed_page,
        ):
            return self._skip_no_change_result(
                fetch_result=fetch_result,
                parsed_page=parsed_page,
                first_page_fingerprint_sha256=first_page_fingerprint_sha256,
                attempt_log=attempt_log,
                page_logs=page_logs,
            )
        if parsed_page.state not in {ParseState.OK, ParseState.NO_RESULTS}:
            return self._initial_failure_result(
                fetch_result=fetch_result,
                parsed_page=parsed_page,
                first_page_fingerprint_sha256=first_page_fingerprint_sha256,
                start_cstart=start_cstart,
                attempt_log=attempt_log,
                page_logs=page_logs,
            )
        return None

    async def _fetch_and_parse_all_pages_with_retry(self, *, scholar_id: str, start_cstart: int, request_delay_seconds: int, network_error_retries: int, retry_backoff_seconds: float, max_pages: int, page_size: int, previous_initial_page_fingerprint_sha256: str | None = None) -> PagedParseResult:
        bounded_max_pages = max(1, int(max_pages))
        bounded_page_size = max(1, int(page_size))
        fetch_result, parsed_page, first_page_fingerprint_sha256, attempt_log, page_logs = (
            await self._fetch_initial_page_context(
            scholar_id=scholar_id,
            start_cstart=start_cstart,
            bounded_page_size=bounded_page_size,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        ))
        shortcut_result = self._short_circuit_initial_page(
            start_cstart=start_cstart,
            previous_initial_page_fingerprint_sha256=previous_initial_page_fingerprint_sha256,
            fetch_result=fetch_result,
            parsed_page=parsed_page,
            first_page_fingerprint_sha256=first_page_fingerprint_sha256,
            attempt_log=attempt_log,
            page_logs=page_logs,
        )
        if shortcut_result is not None:
            return shortcut_result
        state = self._build_loop_state(
            start_cstart=start_cstart,
            fetch_result=fetch_result,
            parsed_page=parsed_page,
            attempt_log=attempt_log,
            page_logs=page_logs,
        )
        await self._paginate_loop(
            scholar_id=scholar_id,
            state=state,
            bounded_max_pages=bounded_max_pages,
            request_delay_seconds=request_delay_seconds,
            bounded_page_size=bounded_page_size,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        return self._result_from_pagination_state(
            state=state,
            first_page_fetch_result=fetch_result,
            first_page_parsed_page=parsed_page,
            first_page_fingerprint_sha256=first_page_fingerprint_sha256,
        )

    async def _upsert_profile_publications(
        self,
        db_session: AsyncSession,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        publications: list[PublicationCandidate],
    ) -> int:
        seen_publication_ids: set[int] = set()
        discovered_count = 0

        for candidate in publications:
            publication = await self._resolve_publication(db_session, candidate)
            if publication.id in seen_publication_ids:
                continue
            seen_publication_ids.add(publication.id)

            link_result = await db_session.execute(
                select(ScholarPublication).where(
                    ScholarPublication.scholar_profile_id == scholar.id,
                    ScholarPublication.publication_id == publication.id,
                )
            )
            link = link_result.scalar_one_or_none()
            if link is not None:
                continue

            link = ScholarPublication(
                scholar_profile_id=scholar.id,
                publication_id=publication.id,
                is_read=False,
                first_seen_run_id=run.id,
            )
            db_session.add(link)
            discovered_count += 1

            logger.debug(
                "ingestion.publication_discovered",
                extra={
                    "event": "ingestion.publication_discovered",
                    "scholar_profile_id": scholar.id,
                    "publication_id": publication.id,
                    "crawl_run_id": run.id,
                },
            )

        if not scholar.baseline_completed:
            scholar.baseline_completed = True

        return discovered_count

    @staticmethod
    def _validate_publication_candidate(candidate: PublicationCandidate) -> None:
        if not candidate.title.strip():
            raise RuntimeError("Publication candidate is missing title.")
        if candidate.citation_count is not None and int(candidate.citation_count) < 0:
            raise RuntimeError("Publication candidate has negative citation_count.")

    async def _find_publication_by_cluster(
        self,
        db_session: AsyncSession,
        *,
        cluster_id: str | None,
    ) -> Publication | None:
        if not cluster_id:
            return None
        result = await db_session.execute(
            select(Publication).where(Publication.cluster_id == cluster_id)
        )
        return result.scalar_one_or_none()

    async def _find_publication_by_fingerprint(
        self,
        db_session: AsyncSession,
        *,
        fingerprint: str,
    ) -> Publication | None:
        result = await db_session.execute(
            select(Publication).where(Publication.fingerprint_sha256 == fingerprint)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _select_existing_publication(
        *,
        cluster_publication: Publication | None,
        fingerprint_publication: Publication | None,
    ) -> Publication | None:
        if cluster_publication is not None:
            return cluster_publication
        return fingerprint_publication

    async def _create_publication(
        self,
        db_session: AsyncSession,
        *,
        candidate: PublicationCandidate,
        fingerprint: str,
    ) -> Publication:
        publication = Publication(
            cluster_id=candidate.cluster_id,
            fingerprint_sha256=fingerprint,
            title_raw=candidate.title,
            title_normalized=normalize_title(candidate.title),
            year=candidate.year,
            citation_count=int(candidate.citation_count or 0),
            author_text=candidate.authors_text,
            venue_text=candidate.venue_text,
            pub_url=build_publication_url(candidate.title_url),
            pdf_url=build_publication_url(candidate.pdf_url),
        )
        db_session.add(publication)
        await db_session.flush()
        logger.debug(
            "ingestion.publication_created",
            extra={
                "event": "ingestion.publication_created",
                "publication_id": publication.id,
                "cluster_id": publication.cluster_id,
            },
        )
        return publication

    @staticmethod
    def _update_existing_publication(
        *,
        publication: Publication,
        candidate: PublicationCandidate,
    ) -> None:
        if candidate.cluster_id and publication.cluster_id is None:
            publication.cluster_id = candidate.cluster_id
        publication.title_raw = candidate.title
        publication.title_normalized = normalize_title(candidate.title)
        if candidate.year is not None:
            publication.year = candidate.year
        if candidate.citation_count is not None:
            publication.citation_count = int(candidate.citation_count)
        if candidate.authors_text:
            publication.author_text = candidate.authors_text
        if candidate.venue_text:
            publication.venue_text = candidate.venue_text
        if candidate.title_url:
            publication.pub_url = build_publication_url(candidate.title_url)
        if candidate.pdf_url:
            publication.pdf_url = build_publication_url(candidate.pdf_url)

    async def _resolve_publication(
        self,
        db_session: AsyncSession,
        candidate: PublicationCandidate,
    ) -> Publication:
        self._validate_publication_candidate(candidate)
        fingerprint = build_publication_fingerprint(candidate)
        cluster_publication = await self._find_publication_by_cluster(
            db_session,
            cluster_id=candidate.cluster_id,
        )
        fingerprint_publication = await self._find_publication_by_fingerprint(
            db_session,
            fingerprint=fingerprint,
        )
        publication = self._select_existing_publication(
            cluster_publication=cluster_publication,
            fingerprint_publication=fingerprint_publication,
        )
        if publication is None:
            return await self._create_publication(
                db_session,
                candidate=candidate,
                fingerprint=fingerprint,
            )
        self._update_existing_publication(
            publication=publication,
            candidate=candidate,
        )
        return publication

    def _resolve_run_status(
        self,
        *,
        scholar_count: int,
        succeeded_count: int,
        failed_count: int,
        partial_count: int,
    ) -> RunStatus:
        if scholar_count == 0:
            return RunStatus.SUCCESS
        if failed_count == scholar_count:
            return RunStatus.FAILED
        if failed_count > 0 or partial_count > 0:
            return RunStatus.PARTIAL_FAILURE
        if succeeded_count > 0:
            return RunStatus.SUCCESS
        return RunStatus.FAILED

    def _resolve_continuation_queue_target(
        self,
        *,
        outcome: str,
        state: str,
        pagination_truncated_reason: str | None,
        continuation_cstart: int | None,
        fallback_cstart: int,
    ) -> tuple[str | None, int]:
        if outcome == "partial":
            reason = (pagination_truncated_reason or "").strip()
            if reason in RESUMABLE_PARTIAL_REASONS or reason.startswith(
                RESUMABLE_PARTIAL_REASON_PREFIXES
            ):
                return reason, queue_service.normalize_cstart(
                    continuation_cstart if continuation_cstart is not None else fallback_cstart
                )
            return None, queue_service.normalize_cstart(fallback_cstart)

        if outcome == "failed" and state == ParseState.NETWORK_ERROR.value:
            return "network_error_retry", queue_service.normalize_cstart(
                continuation_cstart if continuation_cstart is not None else fallback_cstart
            )

        return None, queue_service.normalize_cstart(fallback_cstart)

    def _build_failure_debug_context(
        self,
        *,
        fetch_result: FetchResult,
        parsed_page: ParsedProfilePage,
        attempt_log: list[dict[str, Any]],
        page_logs: list[dict[str, Any]] | None = None,
        exception: Exception | None = None,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "requested_url": fetch_result.requested_url,
            "final_url": fetch_result.final_url,
            "status_code": fetch_result.status_code,
            "fetch_error": fetch_result.error,
            "state_reason": parsed_page.state_reason,
            "profile_name": parsed_page.profile_name,
            "profile_image_url": parsed_page.profile_image_url,
            "articles_range": parsed_page.articles_range,
            "has_show_more_button": parsed_page.has_show_more_button,
            "has_operation_error_banner": parsed_page.has_operation_error_banner,
            "warning_codes": parsed_page.warnings,
            "marker_counts_nonzero": {
                key: value for key, value in parsed_page.marker_counts.items() if value > 0
            },
            "body_length": len(fetch_result.body),
            "body_sha256": hashlib.sha256(fetch_result.body.encode("utf-8")).hexdigest()
            if fetch_result.body
            else None,
            "body_excerpt": _build_body_excerpt(fetch_result.body),
            "attempt_log": attempt_log,
        }
        if page_logs:
            context["page_logs"] = page_logs
        if exception is not None:
            context["exception_type"] = type(exception).__name__
            context["exception_message"] = str(exception)
        return context

    async def _try_acquire_user_lock(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
    ) -> bool:
        result = await db_session.execute(
            text(
                "SELECT pg_try_advisory_xact_lock(:namespace, :user_key)"
            ),
            {
                "namespace": RUN_LOCK_NAMESPACE,
                "user_key": int(user_id),
            },
        )
        return bool(result.scalar_one())


def normalize_title(value: str) -> str:
    lowered = value.lower()
    cleaned = TITLE_ALNUM_RE.sub("", lowered)
    return cleaned


def _first_author_last_name(authors_text: str | None) -> str:
    if not authors_text:
        return ""
    first_author = authors_text.split(",", maxsplit=1)[0].strip().lower()
    words = WORD_RE.findall(first_author)
    if not words:
        return ""
    return words[-1]


def _first_venue_word(venue_text: str | None) -> str:
    if not venue_text:
        return ""
    words = WORD_RE.findall(venue_text.lower())
    if not words:
        return ""
    return words[0]


def build_publication_fingerprint(candidate: PublicationCandidate) -> str:
    canonical = "|".join(
        [
            normalize_title(candidate.title),
            str(candidate.year) if candidate.year is not None else "",
            _first_author_last_name(candidate.authors_text),
            _first_venue_word(candidate.venue_text),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_initial_page_fingerprint(parsed_page: ParsedProfilePage) -> str | None:
    if parsed_page.state not in {ParseState.OK, ParseState.NO_RESULTS}:
        return None

    normalized_rows: list[dict[str, Any]] = []
    for publication in parsed_page.publications[:INITIAL_PAGE_FINGERPRINT_MAX_PUBLICATIONS]:
        normalized_rows.append(
            {
                "cluster_id": publication.cluster_id or "",
                "title_normalized": normalize_title(publication.title),
                "year": publication.year,
                "citation_count": publication.citation_count,
            }
        )

    payload = {
        "state": parsed_page.state.value,
        "articles_range": parsed_page.articles_range or "",
        "has_show_more_button": parsed_page.has_show_more_button,
        "profile_name": parsed_page.profile_name or "",
        "publications": normalized_rows,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_publication_url(path_or_url: str | None) -> str | None:
    if not path_or_url:
        return None
    return urljoin("https://scholar.google.com", path_or_url)


def _next_cstart_value(*, articles_range: str | None, fallback: int) -> int:
    if articles_range:
        numbers = re.findall(r"\d+", articles_range)
        if len(numbers) >= 2:
            try:
                return int(numbers[1])
            except ValueError:
                pass
    return int(fallback)


def _dedupe_publication_candidates(
    publications: list[PublicationCandidate],
) -> list[PublicationCandidate]:
    deduped: list[PublicationCandidate] = []
    seen: set[str] = set()
    for publication in publications:
        if publication.cluster_id:
            identity = f"cluster:{publication.cluster_id}"
        else:
            identity = "|".join(
                [
                    "fallback",
                    normalize_title(publication.title),
                    str(publication.year) if publication.year is not None else "",
                    publication.authors_text or "",
                    publication.venue_text or "",
                ]
            )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(publication)
    return deduped


def _build_body_excerpt(body: str, *, max_chars: int = 220) -> str | None:
    if not body:
        return None
    flattened = SPACE_RE.sub(" ", HTML_TAG_RE.sub(" ", body)).strip()
    if not flattened:
        return None
    if len(flattened) <= max_chars:
        return flattened
    return f"{flattened[:max_chars - 1]}..."
