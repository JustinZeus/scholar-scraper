from __future__ import annotations

import asyncio
from dataclasses import dataclass
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
from app.services.scholar_parser import (
    ParseState,
    ParsedProfilePage,
    PublicationCandidate,
    parse_profile_page,
)
from app.services.scholar_source import FetchResult, ScholarSource

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


class RunAlreadyInProgressError(RuntimeError):
    """Raised when a run lock for a user is already held by another process."""


class ScholarIngestionService:
    def __init__(self, *, source: ScholarSource) -> None:
        self._source = source

    async def run_for_user(
        self,
        db_session: AsyncSession,
        *,
        user_id: int,
        trigger_type: RunTriggerType,
        request_delay_seconds: int,
        network_error_retries: int = 1,
        retry_backoff_seconds: float = 1.0,
        max_pages_per_scholar: int = 30,
        page_size: int = 100,
        scholar_profile_ids: set[int] | None = None,
        start_cstart_by_scholar_id: dict[int, int] | None = None,
        auto_queue_continuations: bool = True,
        queue_delay_seconds: int = 60,
        idempotency_key: str | None = None,
    ) -> RunExecutionSummary:
        lock_acquired = await self._try_acquire_user_lock(
            db_session,
            user_id=user_id,
        )
        if not lock_acquired:
            raise RunAlreadyInProgressError(f"Run already in progress for user_id={user_id}.")

        filtered_scholar_ids = (
            {int(value) for value in scholar_profile_ids}
            if scholar_profile_ids is not None
            else None
        )
        start_cstart_map = {
            int(key): max(0, int(value))
            for key, value in (start_cstart_by_scholar_id or {}).items()
        }

        scholars_stmt = (
            select(ScholarProfile)
            .where(
                ScholarProfile.user_id == user_id,
                ScholarProfile.is_enabled.is_(True),
            )
            .order_by(ScholarProfile.created_at.asc(), ScholarProfile.id.asc())
        )
        if filtered_scholar_ids is not None:
            scholars_stmt = scholars_stmt.where(
                ScholarProfile.id.in_(filtered_scholar_ids)
            )

        scholars_result = await db_session.execute(
            scholars_stmt
        )
        scholars = list(scholars_result.scalars().all())
        if filtered_scholar_ids is not None:
            found_ids = {int(scholar.id) for scholar in scholars}
            missing_ids = filtered_scholar_ids - found_ids
            for scholar_profile_id in missing_ids:
                await queue_service.clear_job_for_scholar(
                    db_session,
                    user_id=user_id,
                    scholar_profile_id=scholar_profile_id,
                )
        logger.info(
            "ingestion.run_started",
            extra={
                "event": "ingestion.run_started",
                "user_id": user_id,
                "trigger_type": trigger_type.value,
                "scholar_count": len(scholars),
                "is_filtered_run": filtered_scholar_ids is not None,
                "request_delay_seconds": request_delay_seconds,
                "network_error_retries": network_error_retries,
                "retry_backoff_seconds": retry_backoff_seconds,
                "max_pages_per_scholar": max_pages_per_scholar,
                "page_size": page_size,
                "idempotency_key": idempotency_key,
            },
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
        await db_session.flush()

        succeeded_count = 0
        failed_count = 0
        partial_count = 0
        scholar_results: list[dict[str, Any]] = []

        for index, scholar in enumerate(scholars):
            if index > 0 and request_delay_seconds > 0:
                await asyncio.sleep(float(request_delay_seconds))

            run_dt = datetime.now(timezone.utc)
            start_cstart = int(start_cstart_map.get(int(scholar.id), 0))

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
            fetch_result = paged_parse_result.fetch_result
            parsed_page = paged_parse_result.parsed_page
            publications = paged_parse_result.publications
            attempt_log = paged_parse_result.attempt_log
            page_logs = paged_parse_result.page_logs

            first_page = paged_parse_result.first_page_parsed_page
            if first_page.profile_name and not (scholar.display_name or "").strip():
                scholar.display_name = first_page.profile_name
            if first_page.profile_image_url:
                scholar.profile_image_url = first_page.profile_image_url
            if paged_parse_result.first_page_fingerprint_sha256:
                scholar.last_initial_page_fingerprint_sha256 = (
                    paged_parse_result.first_page_fingerprint_sha256
                )
            scholar.last_initial_page_checked_at = run_dt

            logger.info(
                "ingestion.scholar_parsed",
                extra={
                    "event": "ingestion.scholar_parsed",
                    "user_id": user_id,
                    "crawl_run_id": run.id,
                    "scholar_profile_id": scholar.id,
                    "scholar_id": scholar.scholar_id,
                    "state": parsed_page.state.value,
                    "publication_count": len(publications),
                    "has_show_more_button": parsed_page.has_show_more_button,
                    "pages_fetched": paged_parse_result.pages_fetched,
                    "pages_attempted": paged_parse_result.pages_attempted,
                    "has_more_remaining": paged_parse_result.has_more_remaining,
                    "pagination_truncated_reason": paged_parse_result.pagination_truncated_reason,
                    "warning_count": len(parsed_page.warnings),
                    "skipped_no_change": paged_parse_result.skipped_no_change,
                },
            )

            result_entry = {
                "scholar_profile_id": scholar.id,
                "scholar_id": scholar.scholar_id,
                "state": parsed_page.state.value,
                "state_reason": parsed_page.state_reason,
                "outcome": "failed",
                "attempt_count": len(attempt_log),
                "publication_count": len(publications),
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
            if paged_parse_result.skipped_no_change:
                scholar.last_run_status = RunStatus.SUCCESS
                scholar.last_run_dt = run_dt
                succeeded_count += 1
                result_entry["state"] = first_page.state.value
                result_entry["state_reason"] = "no_change_initial_page_signature"
                result_entry["outcome"] = "success"
                result_entry["publication_count"] = 0
                result_entry["warnings"] = first_page.warnings
                result_entry["debug"] = {
                    "state_reason": "no_change_initial_page_signature",
                    "first_page_fingerprint_sha256": paged_parse_result.first_page_fingerprint_sha256,
                    "attempt_log": attempt_log,
                    "page_logs": page_logs,
                }
                scholar_results.append(result_entry)
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
                else:
                    cleared = await queue_service.clear_job_for_scholar(
                        db_session,
                        user_id=user_id,
                        scholar_profile_id=scholar.id,
                    )
                    if cleared:
                        result_entry["continuation_cleared"] = True
                continue

            had_page_failure = parsed_page.state not in {ParseState.OK, ParseState.NO_RESULTS}
            has_partial_publication_set = len(publications) > 0 and had_page_failure
            is_partial_due_to_pagination = (
                paged_parse_result.has_more_remaining
                or paged_parse_result.pagination_truncated_reason is not None
            )

            if (not had_page_failure) or has_partial_publication_set:
                try:
                    discovered_publication_count = await self._upsert_profile_publications(
                        db_session,
                        run=run,
                        scholar=scholar,
                        publications=publications,
                    )
                    run.new_pub_count = int(run.new_pub_count or 0) + discovered_publication_count

                    is_partial_scholar = is_partial_due_to_pagination or has_partial_publication_set
                    scholar.last_run_status = (
                        RunStatus.PARTIAL_FAILURE if is_partial_scholar else RunStatus.SUCCESS
                    )
                    scholar.last_run_dt = run_dt
                    succeeded_count += 1
                    result_entry["outcome"] = "partial" if is_partial_scholar else "success"

                    if is_partial_scholar:
                        partial_count += 1
                        result_entry["debug"] = self._build_failure_debug_context(
                            fetch_result=fetch_result,
                            parsed_page=parsed_page,
                            attempt_log=attempt_log,
                            page_logs=page_logs,
                        )
                except Exception as exc:
                    failed_count += 1
                    scholar.last_run_status = RunStatus.FAILED
                    scholar.last_run_dt = run_dt
                    result_entry["state"] = "ingestion_error"
                    result_entry["state_reason"] = "publication_upsert_exception"
                    result_entry["outcome"] = "failed"
                    result_entry["error"] = str(exc)
                    result_entry["debug"] = self._build_failure_debug_context(
                        fetch_result=fetch_result,
                        parsed_page=parsed_page,
                        attempt_log=attempt_log,
                        page_logs=page_logs,
                        exception=exc,
                    )
                    logger.exception(
                        "ingestion.scholar_failed",
                        extra={
                            "event": "ingestion.scholar_failed",
                            "user_id": user_id,
                            "crawl_run_id": run.id,
                            "scholar_profile_id": scholar.id,
                            "scholar_id": scholar.scholar_id,
                        },
                    )
            else:
                failed_count += 1
                scholar.last_run_status = RunStatus.FAILED
                scholar.last_run_dt = run_dt
                result_entry["debug"] = self._build_failure_debug_context(
                    fetch_result=fetch_result,
                    parsed_page=parsed_page,
                    attempt_log=attempt_log,
                    page_logs=page_logs,
                )
                logger.warning(
                    "ingestion.scholar_parse_failed",
                    extra={
                        "event": "ingestion.scholar_parse_failed",
                        "user_id": user_id,
                        "crawl_run_id": run.id,
                        "scholar_profile_id": scholar.id,
                        "scholar_id": scholar.scholar_id,
                        "state": parsed_page.state.value,
                        "state_reason": parsed_page.state_reason,
                        "status_code": fetch_result.status_code,
                    },
                )

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
            else:
                cleared = await queue_service.clear_job_for_scholar(
                    db_session,
                    user_id=user_id,
                    scholar_profile_id=scholar.id,
                )
                if cleared:
                    result_entry["continuation_cleared"] = True

            scholar_results.append(result_entry)

        failed_state_counts: dict[str, int] = {}
        failed_reason_counts: dict[str, int] = {}
        for entry in scholar_results:
            if str(entry.get("outcome", "")) != "failed":
                continue
            state = str(entry.get("state", ""))
            if state not in FAILED_STATES:
                continue
            failed_state_counts[state] = failed_state_counts.get(state, 0) + 1
            reason = str(entry.get("state_reason", "")).strip()
            if reason:
                failed_reason_counts[reason] = failed_reason_counts.get(reason, 0) + 1

        run.end_dt = datetime.now(timezone.utc)
        run.status = self._resolve_run_status(
            scholar_count=len(scholars),
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            partial_count=partial_count,
        )
        run.error_log = {
            "scholar_results": scholar_results,
            "summary": {
                "succeeded_count": succeeded_count,
                "failed_count": failed_count,
                "partial_count": partial_count,
                "failed_state_counts": failed_state_counts,
                "failed_reason_counts": failed_reason_counts,
            },
            "meta": {
                "idempotency_key": idempotency_key,
            }
            if idempotency_key
            else {},
        }

        await db_session.commit()
        logger.info(
            "ingestion.run_completed",
            extra={
                "event": "ingestion.run_completed",
                "user_id": user_id,
                "crawl_run_id": run.id,
                "status": run.status.value,
                "scholar_count": len(scholars),
                "succeeded_count": succeeded_count,
                "failed_count": failed_count,
                "partial_count": partial_count,
                "new_publication_count": run.new_pub_count,
            },
        )

        return RunExecutionSummary(
            crawl_run_id=run.id,
            status=run.status,
            scholar_count=len(scholars),
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            partial_count=partial_count,
            new_publication_count=run.new_pub_count,
        )

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
                {
                    "attempt": attempt_index + 1,
                    "cstart": cstart,
                    "state": parsed_page.state.value,
                    "state_reason": parsed_page.state_reason,
                    "status_code": fetch_result.status_code,
                    "fetch_error": fetch_result.error,
                }
            )

            should_retry = (
                parsed_page.state == ParseState.NETWORK_ERROR
                and attempt_index < max_attempts - 1
            )
            if not should_retry:
                break

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
                    "state_reason": parsed_page.state_reason,
                },
            )
            if sleep_seconds > 0:
                await asyncio.sleep(sleep_seconds)

        if fetch_result is None or parsed_page is None:
            raise RuntimeError("Fetch-and-parse retry loop produced no result.")
        return fetch_result, parsed_page, attempt_log

    async def _fetch_and_parse_all_pages_with_retry(
        self,
        *,
        scholar_id: str,
        start_cstart: int,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        max_pages: int,
        page_size: int,
        previous_initial_page_fingerprint_sha256: str | None = None,
    ) -> PagedParseResult:
        bounded_max_pages = max(1, int(max_pages))
        bounded_page_size = max(1, int(page_size))

        (
            fetch_result,
            parsed_page,
            first_attempt_log,
        ) = await self._fetch_and_parse_page_with_retry(
            scholar_id=scholar_id,
            cstart=start_cstart,
            page_size=bounded_page_size,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        first_page_fetch_result = fetch_result
        first_page_parsed_page = parsed_page
        first_page_fingerprint_sha256 = build_initial_page_fingerprint(parsed_page)

        attempt_log: list[dict[str, Any]] = list(first_attempt_log)
        page_logs: list[dict[str, Any]] = []
        page_logs.append(
            {
                "page": 1,
                "cstart": start_cstart,
                "state": parsed_page.state.value,
                "state_reason": parsed_page.state_reason,
                "status_code": fetch_result.status_code,
                "publication_count": len(parsed_page.publications),
                "articles_range": parsed_page.articles_range,
                "has_show_more_button": parsed_page.has_show_more_button,
                "warning_codes": parsed_page.warnings,
                "attempt_count": len(first_attempt_log),
            }
        )
        pages_attempted = 1

        should_skip_no_change = (
            start_cstart <= 0
            and first_page_fingerprint_sha256 is not None
            and previous_initial_page_fingerprint_sha256 is not None
            and first_page_fingerprint_sha256 == previous_initial_page_fingerprint_sha256
            and parsed_page.state in {ParseState.OK, ParseState.NO_RESULTS}
        )
        if should_skip_no_change:
            return PagedParseResult(
                fetch_result=fetch_result,
                parsed_page=parsed_page,
                first_page_fetch_result=first_page_fetch_result,
                first_page_parsed_page=first_page_parsed_page,
                first_page_fingerprint_sha256=first_page_fingerprint_sha256,
                publications=[],
                attempt_log=attempt_log,
                page_logs=page_logs,
                pages_fetched=1,
                pages_attempted=pages_attempted,
                has_more_remaining=False,
                pagination_truncated_reason=None,
                continuation_cstart=None,
                skipped_no_change=True,
            )

        # Immediate hard failure: nothing to salvage.
        if parsed_page.state not in {ParseState.OK, ParseState.NO_RESULTS}:
            return PagedParseResult(
                fetch_result=fetch_result,
                parsed_page=parsed_page,
                first_page_fetch_result=first_page_fetch_result,
                first_page_parsed_page=first_page_parsed_page,
                first_page_fingerprint_sha256=first_page_fingerprint_sha256,
                publications=[],
                attempt_log=attempt_log,
                page_logs=page_logs,
                pages_fetched=0,
                pages_attempted=pages_attempted,
                has_more_remaining=False,
                pagination_truncated_reason=None,
                continuation_cstart=(
                    start_cstart if parsed_page.state == ParseState.NETWORK_ERROR else None
                ),
                skipped_no_change=False,
            )

        publications = list(parsed_page.publications)
        pages_fetched = 1
        has_more_remaining = False
        pagination_truncated_reason: str | None = None
        continuation_cstart: int | None = None
        current_cstart = start_cstart
        next_cstart = _next_cstart_value(
            articles_range=parsed_page.articles_range,
            fallback=current_cstart + len(parsed_page.publications),
        )

        while parsed_page.has_show_more_button:
            if pages_fetched >= bounded_max_pages:
                has_more_remaining = True
                pagination_truncated_reason = "max_pages_reached"
                continuation_cstart = next_cstart if next_cstart > current_cstart else current_cstart
                break
            if next_cstart <= current_cstart:
                has_more_remaining = True
                pagination_truncated_reason = "pagination_cursor_stalled"
                continuation_cstart = current_cstart
                break
            if request_delay_seconds > 0:
                await asyncio.sleep(float(request_delay_seconds))

            current_cstart = next_cstart
            (
                page_fetch_result,
                page_parsed,
                page_attempt_log,
            ) = await self._fetch_and_parse_page_with_retry(
                scholar_id=scholar_id,
                cstart=current_cstart,
                page_size=bounded_page_size,
                network_error_retries=network_error_retries,
                retry_backoff_seconds=retry_backoff_seconds,
            )

            pages_attempted += 1
            attempt_log.extend(page_attempt_log)
            page_logs.append(
                {
                    "page": pages_attempted,
                    "cstart": current_cstart,
                    "state": page_parsed.state.value,
                    "state_reason": page_parsed.state_reason,
                    "status_code": page_fetch_result.status_code,
                    "publication_count": len(page_parsed.publications),
                    "articles_range": page_parsed.articles_range,
                    "has_show_more_button": page_parsed.has_show_more_button,
                    "warning_codes": page_parsed.warnings,
                    "attempt_count": len(page_attempt_log),
                }
            )

            fetch_result = page_fetch_result
            parsed_page = page_parsed
            if parsed_page.state not in {ParseState.OK, ParseState.NO_RESULTS}:
                has_more_remaining = True
                pagination_truncated_reason = f"page_state_{parsed_page.state.value}"
                continuation_cstart = current_cstart
                break

            # Google may keep a stale/disabled "show more" marker while returning an empty tail page.
            # Treat this as a terminal page to avoid false cursor-stalled partial runs.
            if parsed_page.state == ParseState.NO_RESULTS and len(parsed_page.publications) == 0:
                pages_fetched += 1
                break

            pages_fetched += 1
            publications.extend(parsed_page.publications)
            next_cstart = _next_cstart_value(
                articles_range=parsed_page.articles_range,
                fallback=current_cstart + len(parsed_page.publications),
            )

        return PagedParseResult(
            fetch_result=fetch_result,
            parsed_page=parsed_page,
            first_page_fetch_result=first_page_fetch_result,
            first_page_parsed_page=first_page_parsed_page,
            first_page_fingerprint_sha256=first_page_fingerprint_sha256,
            publications=_dedupe_publication_candidates(publications),
            attempt_log=attempt_log,
            page_logs=page_logs,
            pages_fetched=pages_fetched,
            pages_attempted=pages_attempted,
            has_more_remaining=has_more_remaining,
            pagination_truncated_reason=pagination_truncated_reason,
            continuation_cstart=continuation_cstart,
            skipped_no_change=False,
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

    async def _resolve_publication(
        self,
        db_session: AsyncSession,
        candidate: PublicationCandidate,
    ) -> Publication:
        fingerprint = build_publication_fingerprint(candidate)

        publication: Publication | None = None
        cluster_publication: Publication | None = None

        if candidate.cluster_id:
            cluster_result = await db_session.execute(
                select(Publication).where(Publication.cluster_id == candidate.cluster_id)
            )
            cluster_publication = cluster_result.scalar_one_or_none()
            publication = cluster_publication

        if publication is None:
            fingerprint_result = await db_session.execute(
                select(Publication).where(Publication.fingerprint_sha256 == fingerprint)
            )
            publication = fingerprint_result.scalar_one_or_none()

        if publication is not None and cluster_publication is not None and publication.id != cluster_publication.id:
            publication = cluster_publication

        if publication is None:
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
                pdf_url=None,
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
