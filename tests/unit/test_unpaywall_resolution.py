from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.domains.publications.types import PublicationListItem
from app.services.domains.unpaywall import application as unpaywall_app


class _DummyAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _item(publication_id: int) -> PublicationListItem:
    return PublicationListItem(
        publication_id=publication_id,
        scholar_profile_id=1,
        scholar_label="Shinya Yamanaka",
        title="Induction of pluripotent stem cells",
        year=2007,
        citation_count=1000,
        venue_text="Cell",
        pub_url="https://doi.org/10.1016/j.cell.2007.11.019",
        doi=None,
        pdf_url=None,
        is_read=False,
        first_seen_at=datetime.now(timezone.utc),
        is_new_in_latest_run=True,
    )


@pytest.mark.asyncio
async def test_unpaywall_resolve_prefers_direct_pdf_without_landing_crawl(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "doi": "10.1016/j.cell.2007.11.019",
        "best_oa_location": {
            "url_for_pdf": "https://oa.example.org/article.pdf",
            "url": "https://oa.example.org/landing",
        },
    }

    async def _fake_resolve_item_payload(**_kwargs):
        return payload, False

    async def _fail_crawl(_client, *, page_url: str):
        raise AssertionError(f"unexpected landing crawl: {page_url}")

    monkeypatch.setattr(unpaywall_app, "_resolve_item_payload", _fake_resolve_item_payload)
    monkeypatch.setattr(unpaywall_app, "resolve_pdf_from_landing_page", _fail_crawl)
    monkeypatch.setattr("httpx.AsyncClient", _DummyAsyncClient)
    resolved = await unpaywall_app.resolve_publication_oa_metadata([_item(1)], request_email="user@example.com")
    assert resolved == {1: ("10.1016/j.cell.2007.11.019", "https://oa.example.org/article.pdf")}


@pytest.mark.asyncio
async def test_unpaywall_resolve_crawls_landing_page_when_pdf_url_is_not_direct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "doi": "10.1016/j.cell.2007.11.019",
        "best_oa_location": {
            "url_for_pdf": "https://oa.example.org/view?paper=42",
            "url": "https://oa.example.org/landing/42",
        },
    }
    crawled_pages: list[str] = []

    async def _fake_resolve_item_payload(**_kwargs):
        return payload, False

    async def _fake_crawl(_client, *, page_url: str):
        crawled_pages.append(page_url)
        return "https://oa.example.org/files/paper-42.pdf"

    monkeypatch.setattr(unpaywall_app, "_resolve_item_payload", _fake_resolve_item_payload)
    monkeypatch.setattr(unpaywall_app, "resolve_pdf_from_landing_page", _fake_crawl)
    monkeypatch.setattr("httpx.AsyncClient", _DummyAsyncClient)
    resolved = await unpaywall_app.resolve_publication_oa_metadata([_item(2)], request_email="user@example.com")
    assert resolved == {2: ("10.1016/j.cell.2007.11.019", "https://oa.example.org/files/paper-42.pdf")}
    assert "https://oa.example.org/landing/42" in crawled_pages
