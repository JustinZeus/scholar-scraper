from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CrawlRun,
    RunStatus,
    ScholarProfile,
)
from app.logging_utils import structured_log
from app.services.ingestion.run_completion import build_failure_debug_context
from app.services.ingestion.types import (
    PagedParseResult,
    ScholarProcessingOutcome,
)
from app.services.scholar.parser import ParseState

logger = logging.getLogger(__name__)


def assert_valid_paged_parse_result(
    *,
    scholar_id: str,
    paged_parse_result: PagedParseResult,
) -> None:
    parsed_page = paged_parse_result.parsed_page
    if parsed_page.state in {ParseState.OK, ParseState.NO_RESULTS} and any(
        code.startswith("layout_") for code in parsed_page.warnings
    ):
        raise RuntimeError(f"Layout warning marked as terminal for scholar_id={scholar_id}.")
    for publication in paged_parse_result.publications:
        if not publication.title.strip():
            raise RuntimeError(f"Malformed publication title for scholar_id={scholar_id}.")
        if publication.citation_count is not None and int(publication.citation_count) < 0:
            raise RuntimeError(f"Negative citation count for scholar_id={scholar_id}.")


def apply_first_page_profile_metadata(
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
    scholar.last_initial_page_checked_at = run_dt


def build_result_entry(
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


def skipped_no_change_outcome(
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


async def upsert_publications_outcome(
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
        return await _upsert_success_or_exception(
            db_session,
            run=run,
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
            has_partial_publication_set=has_partial_set,
        )
    return _parse_failure_outcome(
        scholar=scholar,
        run_dt=run_dt,
        paged_parse_result=paged_parse_result,
        result_entry=result_entry,
    )


async def _upsert_success_or_exception(
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
        return _upsert_success(
            run=run,
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
            has_partial_publication_set=has_partial_publication_set,
        )
    except Exception as exc:
        return _upsert_exception_outcome(
            run=run,
            scholar=scholar,
            run_dt=run_dt,
            paged_parse_result=paged_parse_result,
            result_entry=result_entry,
            exc=exc,
        )


def _upsert_success(
    *,
    run: CrawlRun,
    scholar: ScholarProfile,
    run_dt: datetime,
    paged_parse_result: PagedParseResult,
    result_entry: dict[str, Any],
    has_partial_publication_set: bool,
) -> ScholarProcessingOutcome:
    discovered_count = paged_parse_result.discovered_publication_count
    is_partial = (
        paged_parse_result.has_more_remaining
        or paged_parse_result.pagination_truncated_reason is not None
        or has_partial_publication_set
    )
    scholar.last_run_status = RunStatus.PARTIAL_FAILURE if is_partial else RunStatus.SUCCESS
    scholar.last_run_dt = run_dt
    if not is_partial and paged_parse_result.first_page_fingerprint_sha256:
        scholar.last_initial_page_fingerprint_sha256 = paged_parse_result.first_page_fingerprint_sha256
    result_entry["outcome"] = "partial" if is_partial else "success"
    if is_partial:
        result_entry["debug"] = build_failure_debug_context(
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
    result_entry["debug"] = build_failure_debug_context(
        fetch_result=paged_parse_result.fetch_result,
        parsed_page=paged_parse_result.parsed_page,
        attempt_log=paged_parse_result.attempt_log,
        page_logs=paged_parse_result.page_logs,
        exception=exc,
    )
    structured_log(
        logger,
        "exception",
        "ingestion.scholar_failed",
        crawl_run_id=run.id,
        scholar_profile_id=scholar.id,
        scholar_id=scholar.scholar_id,
    )
    return ScholarProcessingOutcome(result_entry, 0, 1, 0, 0)


def _parse_failure_outcome(
    *,
    scholar: ScholarProfile,
    run_dt: datetime,
    paged_parse_result: PagedParseResult,
    result_entry: dict[str, Any],
) -> ScholarProcessingOutcome:
    scholar.last_run_status = RunStatus.FAILED
    scholar.last_run_dt = run_dt
    result_entry["debug"] = build_failure_debug_context(
        fetch_result=paged_parse_result.fetch_result,
        parsed_page=paged_parse_result.parsed_page,
        attempt_log=paged_parse_result.attempt_log,
        page_logs=paged_parse_result.page_logs,
    )
    structured_log(
        logger,
        "warning",
        "ingestion.scholar_parse_failed",
        scholar_profile_id=scholar.id,
        scholar_id=scholar.scholar_id,
        state=paged_parse_result.parsed_page.state.value,
        state_reason=paged_parse_result.parsed_page.state_reason,
        status_code=paged_parse_result.fetch_result.status_code,
    )
    return ScholarProcessingOutcome(result_entry, 0, 1, 0, 0)


def unexpected_scholar_exception_outcome(
    *,
    run: CrawlRun,
    scholar: ScholarProfile,
    start_cstart: int,
    exc: Exception,
) -> ScholarProcessingOutcome:
    scholar.last_run_status = RunStatus.FAILED
    scholar.last_run_dt = datetime.now(UTC)
    structured_log(
        logger,
        "exception",
        "ingestion.scholar_unexpected_failure",
        crawl_run_id=run.id,
        scholar_profile_id=scholar.id,
        scholar_id=scholar.scholar_id,
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
