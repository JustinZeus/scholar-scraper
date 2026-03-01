from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.logging_utils import structured_log
from app.services.scholar.parser import (
    ParsedProfilePage,
    ParseState,
    ScholarParserError,
    parse_profile_page,
)
from app.services.scholar.source import FetchResult, ScholarSource

logger = logging.getLogger(__name__)


class PageFetcher:
    """Fetches and parses a single Google Scholar profile page with retry logic."""

    def __init__(self, *, source: ScholarSource) -> None:
        self._source = source

    async def fetch_profile_page(
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
                    f"https://scholar.google.com/citations?hl=en&user={scholar_id}&cstart={cstart}&pagesize={page_size}"
                ),
                status_code=None,
                final_url=None,
                body="",
                error="source_does_not_support_pagination",
            )
        except Exception as exc:
            structured_log(
                logger,
                "exception",
                "ingestion.fetch_unexpected_error",
                scholar_id=scholar_id,
                cstart=cstart,
                page_size=page_size,
            )
            return FetchResult(
                requested_url=(
                    f"https://scholar.google.com/citations?hl=en&user={scholar_id}&cstart={cstart}&pagesize={page_size}"
                ),
                status_code=None,
                final_url=None,
                body="",
                error=str(exc),
            )

    # ── Parse helpers ────────────────────────────────────────────────

    def parse_page_or_layout_error(
        self,
        *,
        fetch_result: FetchResult,
    ) -> ParsedProfilePage:
        try:
            return parse_profile_page(fetch_result)
        except ScholarParserError as exc:
            return self._parsed_page_from_parser_error(code=exc.code)

    @staticmethod
    def _parsed_page_from_parser_error(*, code: str) -> ParsedProfilePage:
        return ParsedProfilePage(
            state=ParseState.LAYOUT_CHANGED,
            state_reason=code,
            profile_name=None,
            profile_image_url=None,
            publications=[],
            marker_counts={},
            warnings=[code],
            has_show_more_button=False,
            has_operation_error_banner=False,
            articles_range=None,
        )

    # ── Retry logic ──────────────────────────────────────────────────

    @staticmethod
    def _should_retry(
        *,
        parsed_page: ParsedProfilePage,
        network_attempt_count: int,
        rate_limit_attempt_count: int,
        network_error_retries: int,
        rate_limit_retries: int,
    ) -> bool:
        if parsed_page.state == ParseState.NETWORK_ERROR:
            return network_attempt_count <= network_error_retries
        if (
            parsed_page.state == ParseState.BLOCKED_OR_CAPTCHA
            and parsed_page.state_reason == "blocked_http_429_rate_limited"
        ):
            return rate_limit_attempt_count <= rate_limit_retries
        return False

    @staticmethod
    async def _sleep_backoff(
        *,
        scholar_id: str,
        cstart: int,
        network_attempt_count: int,
        rate_limit_attempt_count: int,
        retry_backoff_seconds: float,
        rate_limit_backoff_seconds: float,
        state_reason: str,
    ) -> None:
        if state_reason == "blocked_http_429_rate_limited":
            sleep_seconds = rate_limit_backoff_seconds * rate_limit_attempt_count
            attempt_label = rate_limit_attempt_count
        else:
            sleep_seconds = retry_backoff_seconds * (2 ** (network_attempt_count - 1))
            attempt_label = network_attempt_count

        structured_log(
            logger,
            "warning",
            "ingestion.scholar_retry_scheduled",
            scholar_id=scholar_id,
            cstart=cstart,
            attempt_count=attempt_label,
            sleep_seconds=sleep_seconds,
            state_reason=state_reason,
        )
        if sleep_seconds > 0:
            await asyncio.sleep(sleep_seconds)

    @staticmethod
    def _classify_attempt(
        parsed_page: ParsedProfilePage,
        *,
        network_attempts: int,
        rate_limit_attempts: int,
    ) -> tuple[int, int, int]:
        if parsed_page.state == ParseState.NETWORK_ERROR:
            network_attempts += 1
            return network_attempts, rate_limit_attempts, network_attempts
        if (
            parsed_page.state == ParseState.BLOCKED_OR_CAPTCHA
            and parsed_page.state_reason == "blocked_http_429_rate_limited"
        ):
            rate_limit_attempts += 1
            return network_attempts, rate_limit_attempts, rate_limit_attempts
        return network_attempts, rate_limit_attempts, network_attempts + rate_limit_attempts + 1

    async def fetch_and_parse_with_retry(
        self,
        *,
        scholar_id: str,
        cstart: int,
        page_size: int,
        network_error_retries: int,
        retry_backoff_seconds: float,
        rate_limit_retries: int,
        rate_limit_backoff_seconds: float,
    ) -> tuple[FetchResult, ParsedProfilePage, list[dict[str, Any]]]:
        network_attempts = 0
        rate_limit_attempts = 0
        attempt_log: list[dict[str, Any]] = []
        fetch_result: FetchResult | None = None
        parsed_page: ParsedProfilePage | None = None

        while True:
            fetch_result = await self.fetch_profile_page(
                scholar_id=scholar_id,
                cstart=cstart,
                page_size=page_size,
            )
            parsed_page = self.parse_page_or_layout_error(fetch_result=fetch_result)
            network_attempts, rate_limit_attempts, total_attempts = self._classify_attempt(
                parsed_page, network_attempts=network_attempts, rate_limit_attempts=rate_limit_attempts
            )
            attempt_log.append(
                {
                    "attempt": total_attempts,
                    "cstart": cstart,
                    "state": parsed_page.state.value,
                    "state_reason": parsed_page.state_reason,
                    "status_code": fetch_result.status_code,
                    "fetch_error": fetch_result.error,
                }
            )
            if not self._should_retry(
                parsed_page=parsed_page,
                network_attempt_count=network_attempts,
                rate_limit_attempt_count=rate_limit_attempts,
                network_error_retries=network_error_retries,
                rate_limit_retries=rate_limit_retries,
            ):
                break
            await self._sleep_backoff(
                scholar_id=scholar_id,
                cstart=cstart,
                network_attempt_count=network_attempts,
                rate_limit_attempt_count=rate_limit_attempts,
                retry_backoff_seconds=max(float(retry_backoff_seconds), 0.0),
                rate_limit_backoff_seconds=max(float(rate_limit_backoff_seconds), 0.0),
                state_reason=parsed_page.state_reason,
            )

        if fetch_result is None or parsed_page is None:
            raise RuntimeError("Fetch-and-parse retry loop produced no result.")
        return fetch_result, parsed_page, attempt_log
