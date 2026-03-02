from __future__ import annotations

from typing import Any

import pytest

from app.services.arxiv import application as arxiv_application
from app.services.arxiv import gateway as arxiv_gateway
from app.services.arxiv.types import ArxivEntry, ArxivFeed, ArxivOpenSearchMeta
from app.settings import settings


def _item(*, title: str = "A Test Paper", scholar_label: str = "Ada Lovelace") -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(title=title, scholar_label=scholar_label)


def test_get_arxiv_gateway_returns_cached_instance() -> None:
    previous = arxiv_gateway.set_arxiv_gateway(None)
    try:
        first = arxiv_gateway.get_arxiv_gateway()
        second = arxiv_gateway.get_arxiv_gateway()
        assert first is second
    finally:
        arxiv_gateway.set_arxiv_gateway(previous)


@pytest.mark.asyncio
async def test_application_discover_uses_gateway_override() -> None:
    class FakeGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[object, str | None, float | None]] = []

        async def discover_arxiv_id_for_publication(
            self,
            *,
            item,
            request_email: str | None = None,
            timeout_seconds: float | None = None,
            max_results: int | None = None,
        ) -> str | None:
            self.calls.append((item, request_email, timeout_seconds))
            return "1234.5678"

    fake_gateway = FakeGateway()
    previous = arxiv_gateway.set_arxiv_gateway(fake_gateway)
    try:
        result = await arxiv_application.discover_arxiv_id_for_publication(
            item=_item(),
            request_email="user@example.com",
            timeout_seconds=7.0,
        )
        assert result == "1234.5678"
        assert fake_gateway.calls
        assert fake_gateway.calls[0][1] == "user@example.com"
        assert fake_gateway.calls[0][2] == 7.0
    finally:
        arxiv_gateway.set_arxiv_gateway(previous)


@pytest.mark.asyncio
async def test_http_gateway_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        async def search(self, **kwargs):
            self.calls += 1
            return ArxivFeed()

    previous_enabled = bool(settings.arxiv_enabled)
    fake_client = FakeClient()
    object.__setattr__(settings, "arxiv_enabled", False)
    try:
        gateway = arxiv_gateway.HttpArxivGateway(client=fake_client)  # type: ignore[arg-type]
        result = await gateway.discover_arxiv_id_for_publication(item=_item())
        assert result is None
        assert fake_client.calls == 0
    finally:
        object.__setattr__(settings, "arxiv_enabled", previous_enabled)


@pytest.mark.asyncio
async def test_http_gateway_uses_client_search_for_discovery() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def search(self, **kwargs):
            self.calls.append(kwargs)
            return ArxivFeed(
                entries=[
                    ArxivEntry(
                        entry_id_url="https://arxiv.org/abs/1234.5678v1",
                        arxiv_id="1234.5678v1",
                        title="Paper",
                        summary="",
                        published=None,
                        updated=None,
                    )
                ],
                opensearch=ArxivOpenSearchMeta(total_results=1, start_index=0, items_per_page=1),
            )

    fake_client = FakeClient()
    gateway = arxiv_gateway.HttpArxivGateway(client=fake_client)  # type: ignore[arg-type]
    result = await gateway.discover_arxiv_id_for_publication(
        item=_item(title="My Paper", scholar_label="Ada Lovelace"),
        request_email="user@example.com",
        timeout_seconds=2.0,
        max_results=4,
    )

    assert result == "1234.5678v1"
    assert fake_client.calls
    first_call = fake_client.calls[0]
    assert first_call["query"] == 'ti:"My Paper" AND au:"lovelace"'
    assert first_call["request_email"] == "user@example.com"
    assert first_call["timeout_seconds"] == 2.0
    assert first_call["max_results"] == 4


def test_build_arxiv_query_normalizes_noisy_mojibake_title() -> None:
    noisy = "  Graphâ€“Neural   Networks  Survey  "
    clean = "Graph Neural Networks Survey"

    assert arxiv_gateway.build_arxiv_query(noisy, None) == arxiv_gateway.build_arxiv_query(clean, None)
