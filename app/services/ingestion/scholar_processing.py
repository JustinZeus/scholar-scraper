from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CrawlRun,
    RunStatus,
    ScholarProfile,
)
from app.logging_utils import structured_log
from app.services.ingestion import queue as queue_service
from app.services.ingestion.constants import (
    RESUMABLE_PARTIAL_REASON_PREFIXES,
    RESUMABLE_PARTIAL_REASONS,
)
from app.services.ingestion.pagination import PaginationEngine
from app.services.ingestion.publication_upsert import upsert_profile_publications
from app.services.ingestion.run_completion import apply_outcome_to_progress
from app.services.ingestion.scholar_outcomes import (
    apply_first_page_profile_metadata,
    assert_valid_paged_parse_result,
    build_result_entry,
    skipped_no_change_outcome,
    unexpected_scholar_exception_outcome,
    upsert_publications_outcome,
)
from app.services.ingestion.types import (
    PagedParseResult,
    RunProgress,
    ScholarProcessingOutcome,
)
from app.services.scholar.parser import ParseState
from app.services.scholar.state_detection import is_hard_challenge_reason

logger = logging.getLogger(__name__)


async def sync_continuation_queue(
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
    queue_reason, queue_cstart = resolve_continuation_queue_target(
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


def resolve_continuation_queue_target(
    *,
    outcome: str,
    state: str,
    pagination_truncated_reason: str | None,
    continuation_cstart: int | None,
    fallback_cstart: int,
) -> tuple[str | None, int]:
    if outcome == "partial":
        reason = (pagination_truncated_reason or "").strip()
        if reason in RESUMABLE_PARTIAL_REASONS or reason.startswith(RESUMABLE_PARTIAL_REASON_PREFIXES):
            return reason, queue_service.normalize_cstart(
                continuation_cstart if continuation_cstart is not None else fallback_cstart
            )
        return None, queue_service.normalize_cstart(fallback_cstart)

    if outcome == "failed" and state == ParseState.NETWORK_ERROR.value:
        return "network_error_retry", queue_service.normalize_cstart(
            continuation_cstart if continuation_cstart is not None else fallback_cstart
        )

    return None, queue_service.normalize_cstart(fallback_cstart)


async def process_scholar(
    db_session: AsyncSession,
    *,
    pagination: PaginationEngine,
    run: CrawlRun,
    scholar: ScholarProfile,
    user_id: int,
    request_delay_seconds: int,
    network_error_retries: int,
    retry_backoff_seconds: float,
    rate_limit_retries: int,
    rate_limit_backoff_seconds: float,
    max_pages_per_scholar: int,
    page_size: int,
    start_cstart: int,
    auto_queue_continuations: bool,
    queue_delay_seconds: int,
) -> ScholarProcessingOutcome:
    try:
        run_dt, paged_parse_result, result_entry = await _fetch_and_prepare_scholar_result(
            db_session,
            pagination=pagination,
            run=run,
            scholar=scholar,
            user_id=user_id,
            start_cstart=start_cstart,
            request_delay_seconds=request_delay_seconds,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
            max_pages_per_scholar=max_pages_per_scholar,
            page_size=page_size,
        )
        outcome = await _resolve_scholar_outcome(
            db_session,
            run=run,
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
        )
        await sync_continuation_queue(
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
    except (OperationalError, InterfaceError):
        raise
    except Exception as exc:
        return unexpected_scholar_exception_outcome(
            run=run,
            scholar=scholar,
            start_cstart=start_cstart,
            exc=exc,
        )


async def _fetch_and_prepare_scholar_result(
    db_session: AsyncSession,
    *,
    pagination: PaginationEngine,
    run: CrawlRun,
    scholar: ScholarProfile,
    user_id: int,
    start_cstart: int,
    request_delay_seconds: int,
    network_error_retries: int,
    retry_backoff_seconds: float,
    rate_limit_retries: int,
    rate_limit_backoff_seconds: float,
    max_pages_per_scholar: int,
    page_size: int,
) -> tuple[datetime, PagedParseResult, dict[str, Any]]:
    run_dt = datetime.now(UTC)
    paged_parse_result = await pagination.fetch_and_parse_all_pages(
        scholar=scholar,
        run=run,
        db_session=db_session,
        start_cstart=start_cstart,
        request_delay_seconds=request_delay_seconds,
        network_error_retries=network_error_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        rate_limit_retries=rate_limit_retries,
        rate_limit_backoff_seconds=rate_limit_backoff_seconds,
        max_pages=max_pages_per_scholar,
        page_size=page_size,
        previous_initial_page_fingerprint_sha256=scholar.last_initial_page_fingerprint_sha256,
        upsert_publications_fn=upsert_profile_publications,
    )
    assert_valid_paged_parse_result(scholar_id=scholar.scholar_id, paged_parse_result=paged_parse_result)
    apply_first_page_profile_metadata(scholar=scholar, paged_parse_result=paged_parse_result, run_dt=run_dt)
    parsed_page = paged_parse_result.parsed_page
    structured_log(
        logger,
        "info",
        "ingestion.scholar_parsed",
        user_id=user_id,
        crawl_run_id=run.id,
        scholar_profile_id=scholar.id,
        scholar_id=scholar.scholar_id,
        state=parsed_page.state.value,
        publication_count=len(paged_parse_result.publications),
        has_show_more_button=parsed_page.has_show_more_button,
        pages_fetched=paged_parse_result.pages_fetched,
        pages_attempted=paged_parse_result.pages_attempted,
        has_more_remaining=paged_parse_result.has_more_remaining,
        pagination_truncated_reason=paged_parse_result.pagination_truncated_reason,
        warning_count=len(parsed_page.warnings),
        skipped_no_change=paged_parse_result.skipped_no_change,
    )
    result_entry = build_result_entry(
        scholar=scholar,
        start_cstart=start_cstart,
        paged_parse_result=paged_parse_result,
    )
    return run_dt, paged_parse_result, result_entry


async def _resolve_scholar_outcome(
    db_session: AsyncSession,
    *,
    run: CrawlRun,
    scholar: ScholarProfile,
    run_dt: datetime,
    paged_parse_result: PagedParseResult,
    result_entry: dict[str, Any],
) -> ScholarProcessingOutcome:
    if paged_parse_result.skipped_no_change:
        return skipped_no_change_outcome(
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
        )
    return await upsert_publications_outcome(
        db_session,
        run=run,
        scholar=scholar,
        run_dt=run_dt,
        paged_parse_result=paged_parse_result,
        result_entry=result_entry,
    )


def _is_hard_challenge_outcome(outcome: ScholarProcessingOutcome) -> bool:
    entry = outcome.result_entry
    return str(entry.get("state", "")) == ParseState.BLOCKED_OR_CAPTCHA.value and is_hard_challenge_reason(
        str(entry.get("state_reason", ""))
    )


async def _run_first_pass(
    db_session: AsyncSession,
    *,
    scholars: list[ScholarProfile],
    pagination: PaginationEngine,
    run: CrawlRun,
    user_id: int,
    start_cstart_map: dict[int, int],
    scholar_kwargs: dict[str, Any],
    request_delay_seconds: int,
    queue_delay_seconds: int,
    progress: RunProgress,
) -> dict[int, int]:
    first_pass_cstarts: dict[int, int] = {}
    for index, scholar in enumerate(scholars):
        await db_session.refresh(run)
        if run.status == RunStatus.CANCELED:
            structured_log(logger, "info", "ingestion.run_canceled", run_id=run.id, user_id=user_id)
            return first_pass_cstarts
        if index > 0 and request_delay_seconds > 0:
            jitter = random.uniform(0.0, min(float(request_delay_seconds), 2.0))
            await asyncio.sleep(float(request_delay_seconds) + jitter)
        start_cstart = int(start_cstart_map.get(int(scholar.id), 0))
        outcome = await process_scholar(
            db_session,
            pagination=pagination,
            run=run,
            scholar=scholar,
            user_id=user_id,
            start_cstart=start_cstart,
            max_pages_per_scholar=1,
            auto_queue_continuations=False,
            queue_delay_seconds=queue_delay_seconds,
            **scholar_kwargs,
        )
        apply_outcome_to_progress(progress=progress, outcome=outcome)
        if _is_hard_challenge_outcome(outcome):
            structured_log(
                logger,
                "warning",
                "ingestion.run_aborted_hard_challenge",
                run_id=run.id,
                user_id=user_id,
                scholar_id=scholar.scholar_id,
                state_reason=outcome.result_entry.get("state_reason"),
                scholars_remaining=len(scholars) - index - 1,
            )
            return first_pass_cstarts
        resume_cstart = outcome.result_entry.get("continuation_cstart")
        if resume_cstart is not None and int(resume_cstart) > start_cstart:
            first_pass_cstarts[int(scholar.id)] = int(resume_cstart)
    return first_pass_cstarts


async def _run_depth_pass(
    db_session: AsyncSession,
    *,
    scholars: list[ScholarProfile],
    first_pass_cstarts: dict[int, int],
    pagination: PaginationEngine,
    run: CrawlRun,
    user_id: int,
    scholar_kwargs: dict[str, Any],
    request_delay_seconds: int,
    remaining_max: int,
    auto_queue_continuations: bool,
    queue_delay_seconds: int,
    progress: RunProgress,
) -> None:
    for index, scholar in enumerate(scholars):
        resume_cstart = first_pass_cstarts.get(int(scholar.id))
        if resume_cstart is None:
            continue
        await db_session.refresh(run)
        if run.status == RunStatus.CANCELED:
            structured_log(logger, "info", "ingestion.run_canceled", run_id=run.id, user_id=user_id)
            break
        if index > 0 and request_delay_seconds > 0:
            jitter = random.uniform(0.0, min(float(request_delay_seconds), 2.0))
            await asyncio.sleep(float(request_delay_seconds) + jitter)
        outcome = await process_scholar(
            db_session,
            pagination=pagination,
            run=run,
            scholar=scholar,
            user_id=user_id,
            start_cstart=resume_cstart,
            max_pages_per_scholar=remaining_max,
            auto_queue_continuations=auto_queue_continuations,
            queue_delay_seconds=queue_delay_seconds,
            **scholar_kwargs,
        )
        apply_outcome_to_progress(progress=progress, outcome=outcome)
        if _is_hard_challenge_outcome(outcome):
            structured_log(
                logger,
                "warning",
                "ingestion.run_aborted_hard_challenge",
                run_id=run.id,
                user_id=user_id,
                scholar_id=scholar.scholar_id,
                state_reason=outcome.result_entry.get("state_reason"),
                scholars_remaining=len(scholars) - index - 1,
            )
            break


async def run_scholar_iteration(
    db_session: AsyncSession,
    *,
    pagination: PaginationEngine,
    run: CrawlRun,
    scholars: list[ScholarProfile],
    user_id: int,
    start_cstart_map: dict[int, int],
    request_delay_seconds: int,
    network_error_retries: int,
    retry_backoff_seconds: float,
    rate_limit_retries: int,
    rate_limit_backoff_seconds: float,
    max_pages_per_scholar: int,
    page_size: int,
    auto_queue_continuations: bool,
    queue_delay_seconds: int,
) -> RunProgress:
    progress = RunProgress()
    scholar_kwargs: dict[str, Any] = {
        "request_delay_seconds": request_delay_seconds,
        "network_error_retries": network_error_retries,
        "retry_backoff_seconds": retry_backoff_seconds,
        "rate_limit_retries": rate_limit_retries,
        "rate_limit_backoff_seconds": rate_limit_backoff_seconds,
        "page_size": page_size,
    }
    first_pass_cstarts = await _run_first_pass(
        db_session,
        scholars=scholars,
        pagination=pagination,
        run=run,
        user_id=user_id,
        start_cstart_map=start_cstart_map,
        scholar_kwargs=scholar_kwargs,
        request_delay_seconds=request_delay_seconds,
        queue_delay_seconds=queue_delay_seconds,
        progress=progress,
    )
    remaining_max = max(max_pages_per_scholar - 1, 0)
    if remaining_max <= 0:
        return progress
    await _run_depth_pass(
        db_session,
        scholars=scholars,
        first_pass_cstarts=first_pass_cstarts,
        pagination=pagination,
        run=run,
        user_id=user_id,
        scholar_kwargs=scholar_kwargs,
        request_delay_seconds=request_delay_seconds,
        remaining_max=remaining_max,
        auto_queue_continuations=auto_queue_continuations,
        queue_delay_seconds=queue_delay_seconds,
        progress=progress,
    )
    return progress
