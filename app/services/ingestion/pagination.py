from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.db.models import CrawlRun, RunStatus, ScholarProfile
from app.logging_utils import structured_log
from app.services.ingestion.fingerprints import (
    _dedupe_publication_candidates,
    _next_cstart_value,
    build_initial_page_fingerprint,
)
from app.services.ingestion.page_fetch import PageFetcher
from app.services.ingestion.types import PagedLoopState, PagedParseResult
from app.services.scholar.parser import ParsedProfilePage, ParseState
from app.services.scholar.source import FetchResult, ScholarSource

logger = logging.getLogger(__name__)


class PaginationEngine:
    """Fetches and paginates Google Scholar profile pages.

    Pure HTTP + parsing — no DB writes except via the provided upsert callback.
    """

    def __init__(self, *, source: ScholarSource) -> None:
        self._source = source
        self._fetcher = PageFetcher(source=source)

    # ── No-change / initial failure short-circuits ───────────────────

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
            discovered_publication_count=0,
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
            discovered_publication_count=0,
        )

    # ── Loop state management ────────────────────────────────────────

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

    # ── Multi-page fetch helpers ─────────────────────────────────────

    async def _fetch_next_page(
        self,
        *,
        scholar_id: str,
        state: PagedLoopState,
        request_delay_seconds: int,
        bounded_page_size: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        rate_limit_retries: int,
        rate_limit_backoff_seconds: float,
    ) -> tuple[FetchResult, ParsedProfilePage, list[dict[str, Any]]]:
        if request_delay_seconds > 0:
            await asyncio.sleep(float(request_delay_seconds))
        state.current_cstart = state.next_cstart
        return await self._fetcher.fetch_and_parse_with_retry(
            scholar_id=scholar_id,
            cstart=state.current_cstart,
            page_size=bounded_page_size,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
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
            {
                "page": state.pages_attempted,
                "cstart": state.current_cstart,
                "state": parsed_page.state.value,
                "state_reason": parsed_page.state_reason,
                "status_code": fetch_result.status_code,
                "publication_count": len(parsed_page.publications),
                "articles_range": parsed_page.articles_range,
                "has_show_more_button": parsed_page.has_show_more_button,
                "warning_codes": parsed_page.warnings,
                "attempt_count": len(page_attempt_log),
            }
        )
        state.fetch_result = fetch_result
        state.parsed_page = parsed_page

    def _handle_page_state_transition(self, *, state: PagedLoopState) -> bool:
        if state.parsed_page.state not in {ParseState.OK, ParseState.NO_RESULTS}:
            self._set_truncated_state(
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
        rate_limit_retries: int,
        rate_limit_backoff_seconds: float,
    ) -> tuple[FetchResult, ParsedProfilePage, str | None, list[dict[str, Any]], list[dict[str, Any]]]:
        fetch_result, parsed_page, first_attempt_log = await self._fetcher.fetch_and_parse_with_retry(
            scholar_id=scholar_id,
            cstart=start_cstart,
            page_size=bounded_page_size,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
        )
        first_page_fingerprint_sha256 = build_initial_page_fingerprint(parsed_page)
        attempt_log = list(first_attempt_log)
        page_logs = [
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
        ]
        return fetch_result, parsed_page, first_page_fingerprint_sha256, attempt_log, page_logs

    # ── Pagination loop ──────────────────────────────────────────────

    @staticmethod
    async def _upsert_page_publications(
        db_session: Any,
        *,
        run: CrawlRun,
        scholar: ScholarProfile,
        publications: list,
        seen_canonical: set[str],
        state: PagedLoopState,
        upsert_publications_fn: Any,
    ) -> None:
        deduped = _dedupe_publication_candidates(list(publications), seen_canonical=seen_canonical)
        if deduped:
            discovered_count = await upsert_publications_fn(db_session, run=run, scholar=scholar, publications=deduped)
            state.discovered_publication_count += discovered_count

    async def _paginate_loop(
        self,
        *,
        scholar: ScholarProfile,
        run: CrawlRun,
        db_session: Any,
        state: PagedLoopState,
        bounded_max_pages: int,
        request_delay_seconds: int,
        bounded_page_size: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        rate_limit_retries: int,
        rate_limit_backoff_seconds: float,
        upsert_publications_fn: Any,
    ) -> None:
        seen_canonical: set[str] = set()

        if state.parsed_page.publications:
            await self._upsert_page_publications(
                db_session,
                run=run,
                scholar=scholar,
                publications=state.parsed_page.publications,
                seen_canonical=seen_canonical,
                state=state,
                upsert_publications_fn=upsert_publications_fn,
            )

        while state.parsed_page.has_show_more_button:
            await db_session.refresh(run)
            if run.status == RunStatus.CANCELED:
                structured_log(
                    logger,
                    "info",
                    "ingestion.pagination_canceled",
                    run_id=run.id,
                )
                self._set_truncated_state(
                    state=state,
                    reason="run_canceled",
                    continuation_cstart=state.current_cstart,
                )
                return

            if self._should_stop_pagination(state=state, bounded_max_pages=bounded_max_pages):
                return
            next_fetch_result, next_parsed_page, next_attempt_log = await self._fetch_next_page(
                scholar_id=scholar.scholar_id,
                state=state,
                request_delay_seconds=request_delay_seconds,
                bounded_page_size=bounded_page_size,
                network_error_retries=network_error_retries,
                retry_backoff_seconds=retry_backoff_seconds,
                rate_limit_retries=rate_limit_retries,
                rate_limit_backoff_seconds=rate_limit_backoff_seconds,
            )
            self._record_next_page(
                state=state,
                fetch_result=next_fetch_result,
                parsed_page=next_parsed_page,
                page_attempt_log=next_attempt_log,
            )

            if self._handle_page_state_transition(state=state):
                return

            if next_parsed_page.publications:
                await self._upsert_page_publications(
                    db_session,
                    run=run,
                    scholar=scholar,
                    publications=next_parsed_page.publications,
                    seen_canonical=seen_canonical,
                    state=state,
                    upsert_publications_fn=upsert_publications_fn,
                )

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
            discovered_publication_count=state.discovered_publication_count,
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

    # ── Public entry point ───────────────────────────────────────────

    async def fetch_and_parse_all_pages(
        self,
        *,
        scholar: ScholarProfile,
        run: CrawlRun,
        db_session: Any,
        start_cstart: int,
        request_delay_seconds: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        rate_limit_retries: int,
        rate_limit_backoff_seconds: float,
        max_pages: int,
        page_size: int,
        previous_initial_page_fingerprint_sha256: str | None = None,
        upsert_publications_fn: Any = None,
    ) -> PagedParseResult:
        bounded_max_pages = max(1, int(max_pages))
        bounded_page_size = max(1, int(page_size))
        (
            fetch_result,
            parsed_page,
            first_page_fingerprint_sha256,
            attempt_log,
            page_logs,
        ) = await self._fetch_initial_page_context(
            scholar_id=scholar.scholar_id,
            start_cstart=start_cstart,
            bounded_page_size=bounded_page_size,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
        )
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
            scholar=scholar,
            run=run,
            db_session=db_session,
            state=state,
            bounded_max_pages=bounded_max_pages,
            request_delay_seconds=request_delay_seconds,
            bounded_page_size=bounded_page_size,
            network_error_retries=network_error_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
            upsert_publications_fn=upsert_publications_fn,
        )
        return self._result_from_pagination_state(
            state=state,
            first_page_fetch_result=fetch_result,
            first_page_parsed_page=parsed_page,
            first_page_fingerprint_sha256=first_page_fingerprint_sha256,
        )
