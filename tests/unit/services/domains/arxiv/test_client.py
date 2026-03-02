from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.arxiv import client as arxiv_client_module
from app.services.arxiv.client import ArxivClient
from app.services.arxiv.errors import ArxivClientValidationError, ArxivRateLimitError
from app.services.arxiv.rate_limit import ArxivCooldownStatus

_CLIENT_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>1</opensearch:totalResults>
  <opensearch:startIndex>0</opensearch:startIndex>
  <opensearch:itemsPerPage>1</opensearch:itemsPerPage>
  <entry>
    <id>http://arxiv.org/abs/9999.0001</id>
    <title>Client Entry</title>
    <summary>Client summary</summary>
  </entry>
</feed>
"""


@pytest.mark.asyncio
async def test_client_search_builds_query_and_sort_params() -> None:
    captured: dict[str, object] = {}

    async def _request_fn(*, params, request_email, timeout_seconds):
        captured["params"] = params
        captured["request_email"] = request_email
        captured["timeout_seconds"] = timeout_seconds
        return httpx.Response(
            200, text=_CLIENT_FEED_XML, request=httpx.Request("GET", "https://export.arxiv.org/api/query")
        )

    client = ArxivClient(request_fn=_request_fn)
    feed = await client.search(
        query='ti:"test"',
        start=5,
        max_results=7,
        sort_by="submittedDate",
        sort_order="ascending",
        request_email="user@example.com",
        timeout_seconds=3.5,
    )

    assert feed.opensearch.total_results == 1
    assert captured["params"] == {
        "search_query": 'ti:"test"',
        "start": 5,
        "max_results": 7,
        "sortBy": "submittedDate",
        "sortOrder": "ascending",
    }
    assert captured["request_email"] == "user@example.com"
    assert captured["timeout_seconds"] == 3.5


@pytest.mark.asyncio
async def test_client_lookup_ids_builds_id_list_param() -> None:
    captured: dict[str, object] = {}

    async def _request_fn(*, params, request_email, timeout_seconds):
        captured["params"] = params
        return httpx.Response(
            200, text=_CLIENT_FEED_XML, request=httpx.Request("GET", "https://export.arxiv.org/api/query")
        )

    client = ArxivClient(request_fn=_request_fn)
    await client.lookup_ids(id_list=["1234.5678", " 9999.0001 "], start=0, max_results=2)
    assert captured["params"] == {"id_list": "1234.5678,9999.0001", "start": 0, "max_results": 2}


@pytest.mark.asyncio
async def test_client_search_rejects_invalid_sort_by() -> None:
    async def _unused_request_fn(*, params, request_email, timeout_seconds):
        return httpx.Response(
            200, text=_CLIENT_FEED_XML, request=httpx.Request("GET", "https://export.arxiv.org/api/query")
        )

    client = ArxivClient(request_fn=_unused_request_fn)
    with pytest.raises(ArxivClientValidationError):
        await client.search(query="x", sort_by="bad")


@pytest.mark.asyncio
async def test_client_lookup_ids_rejects_empty_list() -> None:
    async def _unused_request_fn(*, params, request_email, timeout_seconds):
        return httpx.Response(
            200, text=_CLIENT_FEED_XML, request=httpx.Request("GET", "https://export.arxiv.org/api/query")
        )

    client = ArxivClient(request_fn=_unused_request_fn)
    with pytest.raises(ArxivClientValidationError):
        await client.lookup_ids(id_list=[])


@pytest.mark.asyncio
async def test_client_search_rejects_negative_start() -> None:
    async def _unused_request_fn(*, params, request_email, timeout_seconds):
        return httpx.Response(
            200, text=_CLIENT_FEED_XML, request=httpx.Request("GET", "https://export.arxiv.org/api/query")
        )

    client = ArxivClient(request_fn=_unused_request_fn)
    with pytest.raises(ArxivClientValidationError):
        await client.search(query="ti:test", start=-1)


@pytest.mark.asyncio
async def test_client_propagates_http_status_error() -> None:
    async def _request_fn(*, params, request_email, timeout_seconds):
        request = httpx.Request("GET", "https://export.arxiv.org/api/query")
        return httpx.Response(500, text="error", request=request)

    client = ArxivClient(request_fn=_request_fn)
    with pytest.raises(httpx.HTTPStatusError):
        await client.search(query="ti:test")


@pytest.mark.asyncio
async def test_client_coalesces_concurrent_identical_search_requests() -> None:
    calls = {"count": 0}

    async def _request_fn(*, params, request_email, timeout_seconds):
        calls["count"] += 1
        await asyncio.sleep(0.05)
        request = httpx.Request("GET", "https://export.arxiv.org/api/query")
        return httpx.Response(200, text=_CLIENT_FEED_XML, request=request)

    client = ArxivClient(request_fn=_request_fn)
    await asyncio.gather(
        client.search(query="ti:test"),
        client.search(query="ti:test"),
    )
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_client_logs_cache_hit_and_miss(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    patch_session_factory,
) -> None:
    calls = {"count": 0}
    logged: list[dict[str, object]] = []

    async def _request_fn(*, params, request_email, timeout_seconds):
        calls["count"] += 1
        request = httpx.Request("GET", "https://export.arxiv.org/api/query")
        return httpx.Response(200, text=_CLIENT_FEED_XML, request=request)

    def _capture_log(_msg: str, *args, **kwargs) -> None:
        logged.append({"event": _msg, **(kwargs.get("extra") or {})})

    monkeypatch.setattr("app.services.arxiv.client.logger.info", _capture_log)
    client = ArxivClient(request_fn=_request_fn, cache_enabled=True)
    await client.search(query="ti:test-cache")
    await client.search(query="ti:test-cache")

    events = [str(entry.get("event", "")) for entry in logged]
    assert "arxiv.cache_miss" in events
    assert "arxiv.cache_hit" in events
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_request_feed_skips_live_call_when_global_cooldown_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logged: list[dict[str, object]] = []
    called = {"count": 0}

    async def _cooldown_status(*, now_utc=None):
        _ = now_utc
        return ArxivCooldownStatus(
            is_active=True,
            remaining_seconds=61.0,
            cooldown_until=datetime(2026, 2, 26, 12, 1, tzinfo=UTC),
        )

    async def _unexpected_limit_call(*, fetch, source_path):  # pragma: no cover - defensive
        _ = (fetch, source_path)
        called["count"] += 1
        return httpx.Response(200, text=_CLIENT_FEED_XML)

    def _capture_warning(_msg: str, *args, **kwargs) -> None:
        logged.append({"event": _msg, **(kwargs.get("extra") or {})})

    monkeypatch.setattr(arxiv_client_module, "get_arxiv_cooldown_status", _cooldown_status)
    monkeypatch.setattr(arxiv_client_module, "run_with_global_arxiv_limit", _unexpected_limit_call)
    monkeypatch.setattr("app.services.arxiv.client.logger.warning", _capture_warning)

    with pytest.raises(ArxivRateLimitError):
        await arxiv_client_module._request_arxiv_feed(
            params={"search_query": 'ti:"test"'},
            request_email="user@example.com",
            timeout_seconds=2.0,
        )

    assert called["count"] == 0
    assert [entry.get("event") for entry in logged] == ["arxiv.request_skipped_cooldown"]
