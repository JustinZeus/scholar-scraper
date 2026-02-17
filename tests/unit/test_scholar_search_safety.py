from __future__ import annotations

import pytest

from app.services import scholars as scholar_service
from app.services.scholar_parser import ParseState
from app.services.scholar_source import FetchResult


class StubScholarSource:
    def __init__(self, fetch_results: list[FetchResult]) -> None:
        self._fetch_results = list(fetch_results)
        self.calls = 0

    async def fetch_author_search_html(self, query: str, *, start: int = 0) -> FetchResult:
        assert start == 0
        self.calls += 1
        if not self._fetch_results:
            raise RuntimeError("No stub fetch results configured.")
        index = min(self.calls - 1, len(self._fetch_results) - 1)
        return self._fetch_results[index]


@pytest.fixture(autouse=True)
def reset_author_search_runtime_state() -> None:
    scholar_service._reset_author_search_runtime_state_for_tests()
    yield
    scholar_service._reset_author_search_runtime_state_for_tests()


def _ok_author_search_fetch() -> FetchResult:
    body = (
        "<html><body>"
        '<div class="gsc_1usr">'
        '<img src="/citations/images/avatar_scholar_256.png" />'
        '<a class="gs_ai_name" href="/citations?hl=en&user=abcDEF123456">Ada Lovelace</a>'
        '<div class="gs_ai_aff">Analytical Engine</div>'
        '<div class="gs_ai_eml">Verified email at computing.example</div>'
        '<div class="gs_ai_cby">Cited by 42</div>'
        '<a class="gs_ai_one_int">Mathematics</a>'
        "</div>"
        "</body></html>"
    )
    return FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=ada",
        status_code=200,
        final_url="https://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=ada",
        body=body,
        error=None,
    )


def _blocked_author_search_fetch() -> FetchResult:
    return FetchResult(
        requested_url="https://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=ada",
        status_code=200,
        final_url=(
            "https://accounts.google.com/v3/signin/identifier"
            "?continue=https%3A%2F%2Fscholar.google.com%2Fcitations"
        ),
        body="<html><body>Sign in</body></html>",
        error=None,
    )


@pytest.mark.asyncio
async def test_search_author_candidates_serves_cached_response_for_same_query() -> None:
    source = StubScholarSource([_ok_author_search_fetch()])

    first = await scholar_service.search_author_candidates(
        source=source,
        query="Ada Lovelace",
        limit=10,
        network_error_retries=0,
        retry_backoff_seconds=0.0,
        search_enabled=True,
        cache_ttl_seconds=600,
        blocked_cache_ttl_seconds=60,
        cache_max_entries=64,
        min_interval_seconds=0.0,
        interval_jitter_seconds=0.0,
        cooldown_block_threshold=3,
        cooldown_seconds=300,
    )
    second = await scholar_service.search_author_candidates(
        source=source,
        query="Ada Lovelace",
        limit=10,
        network_error_retries=0,
        retry_backoff_seconds=0.0,
        search_enabled=True,
        cache_ttl_seconds=600,
        blocked_cache_ttl_seconds=60,
        cache_max_entries=64,
        min_interval_seconds=0.0,
        interval_jitter_seconds=0.0,
        cooldown_block_threshold=3,
        cooldown_seconds=300,
    )

    assert first.state == ParseState.OK
    assert second.state == ParseState.OK
    assert source.calls == 1
    assert len(second.candidates) == 1
    assert second.candidates[0].scholar_id == "abcDEF123456"
    assert "author_search_served_from_cache" in second.warnings


@pytest.mark.asyncio
async def test_search_author_candidates_trips_cooldown_after_blocked_responses() -> None:
    source = StubScholarSource([_blocked_author_search_fetch()])

    first = await scholar_service.search_author_candidates(
        source=source,
        query="Blocked Query",
        limit=10,
        network_error_retries=0,
        retry_backoff_seconds=0.0,
        search_enabled=True,
        cache_ttl_seconds=0,
        blocked_cache_ttl_seconds=0,
        cache_max_entries=64,
        min_interval_seconds=0.0,
        interval_jitter_seconds=0.0,
        cooldown_block_threshold=1,
        cooldown_seconds=300,
    )
    second = await scholar_service.search_author_candidates(
        source=source,
        query="Blocked Query",
        limit=10,
        network_error_retries=0,
        retry_backoff_seconds=0.0,
        search_enabled=True,
        cache_ttl_seconds=0,
        blocked_cache_ttl_seconds=0,
        cache_max_entries=64,
        min_interval_seconds=0.0,
        interval_jitter_seconds=0.0,
        cooldown_block_threshold=1,
        cooldown_seconds=300,
    )

    assert first.state == ParseState.BLOCKED_OR_CAPTCHA
    assert "author_search_circuit_breaker_armed" in first.warnings
    assert source.calls == 1

    assert second.state == ParseState.BLOCKED_OR_CAPTCHA
    assert second.state_reason == scholar_service.SEARCH_COOLDOWN_REASON
    assert "author_search_cooldown_active" in second.warnings


@pytest.mark.asyncio
async def test_search_author_candidates_can_be_disabled_by_configuration() -> None:
    source = StubScholarSource([_ok_author_search_fetch()])

    parsed = await scholar_service.search_author_candidates(
        source=source,
        query="Ada Lovelace",
        limit=5,
        network_error_retries=0,
        retry_backoff_seconds=0.0,
        search_enabled=False,
        cache_ttl_seconds=600,
        blocked_cache_ttl_seconds=60,
        cache_max_entries=64,
        min_interval_seconds=0.0,
        interval_jitter_seconds=0.0,
        cooldown_block_threshold=1,
        cooldown_seconds=300,
    )

    assert parsed.state == ParseState.BLOCKED_OR_CAPTCHA
    assert parsed.state_reason == scholar_service.SEARCH_DISABLED_REASON
    assert source.calls == 0
    assert "author_search_disabled_by_configuration" in parsed.warnings
