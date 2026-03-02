from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.arxiv.errors import ArxivRateLimitError
from app.services.publication_identifiers.types import DisplayIdentifier
from app.services.publications import pdf_resolution_pipeline as pipeline
from app.services.unpaywall.application import OaResolutionOutcome


def _row(*, display_identifier: DisplayIdentifier | None = None) -> Any:
    return SimpleNamespace(
        publication_id=1,
        scholar_profile_id=1,
        scholar_label="Ada Lovelace",
        title="A paper",
        year=2024,
        citation_count=0,
        venue_text=None,
        pub_url="https://scholar.google.com/citations?view_op=view_citation&citation_for_view=abc:xyz",
        display_identifier=display_identifier,
        pdf_url=None,
        is_read=False,
        is_favorite=False,
        first_seen_at=datetime(2026, 2, 22, 12, 0, tzinfo=UTC),
        is_new_in_latest_run=True,
    )


def _api_outcome(*, pdf_url: str | None, source: str = "unpaywall") -> OaResolutionOutcome | None:
    if not pdf_url:
        return None
    return OaResolutionOutcome(
        publication_id=1,
        doi="10.1000/example",
        pdf_url=pdf_url,
        failure_reason=None if pdf_url else "no_pdf_found",
        source=source,
        used_crossref=False,
    )


def _oa_fallback_outcome(*, pdf_url: str | None, source: str = "unpaywall") -> OaResolutionOutcome:
    return OaResolutionOutcome(
        publication_id=1,
        doi="10.1000/example",
        pdf_url=pdf_url,
        failure_reason=None if pdf_url else "no_pdf_found",
        source=source,
        used_crossref=False,
    )


@pytest.mark.asyncio
async def test_pipeline_prefers_openalex_before_arxiv(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_openalex(row, request_email: str | None = None, openalex_api_key: str | None = None):
        return _api_outcome(pdf_url="https://oa.example.org/found.pdf", source="openalex")

    async def _fail_arxiv(row, *, request_email: str | None = None, allow_lookup: bool = True):
        _ = (row, request_email, allow_lookup)
        raise AssertionError("arXiv should not run when OpenAlex candidate exists.")

    monkeypatch.setattr(pipeline, "_openalex_outcome", _fake_openalex)
    monkeypatch.setattr(pipeline, "_arxiv_outcome", _fail_arxiv)

    result = await pipeline.resolve_publication_pdf_outcome_for_row(row=_row(), request_email="user@example.com")

    assert result.outcome is not None
    assert result.outcome.pdf_url == "https://oa.example.org/found.pdf"
    assert result.outcome.source == "openalex"


@pytest.mark.asyncio
async def test_pipeline_uses_arxiv_after_openalex_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_openalex(row, request_email: str | None = None, openalex_api_key: str | None = None):
        return None

    async def _fake_arxiv(row, *, request_email: str | None = None, allow_lookup: bool = True):
        _ = allow_lookup
        return _api_outcome(pdf_url="https://arxiv.org/pdf/1234.5678.pdf", source="arxiv")

    async def _fail_oa(*, row, request_email):
        raise AssertionError("Unpaywall should not run when arXiv returns PDF.")

    monkeypatch.setattr(pipeline, "_openalex_outcome", _fake_openalex)
    monkeypatch.setattr(pipeline, "_arxiv_outcome", _fake_arxiv)
    monkeypatch.setattr(pipeline, "_oa_outcome", _fail_oa)

    result = await pipeline.resolve_publication_pdf_outcome_for_row(row=_row(), request_email="user@example.com")

    assert result.outcome is not None
    assert result.outcome.pdf_url == "https://arxiv.org/pdf/1234.5678.pdf"
    assert result.outcome.source == "arxiv"


@pytest.mark.asyncio
async def test_pipeline_uses_unpaywall_after_arxiv_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_openalex(row, request_email: str | None = None, openalex_api_key: str | None = None):
        return None

    async def _fake_arxiv(row, *, request_email: str | None = None, allow_lookup: bool = True):
        _ = (request_email, allow_lookup)
        return None

    async def _fake_oa(*, row, request_email):
        assert request_email == "user@example.com"
        return _oa_fallback_outcome(pdf_url="https://example.org/fallback.pdf", source="unpaywall")

    monkeypatch.setattr(pipeline, "_openalex_outcome", _fake_openalex)
    monkeypatch.setattr(pipeline, "_arxiv_outcome", _fake_arxiv)
    monkeypatch.setattr(pipeline, "_oa_outcome", _fake_oa)

    result = await pipeline.resolve_publication_pdf_outcome_for_row(row=_row(), request_email="user@example.com")

    assert result.outcome is not None
    assert result.outcome.pdf_url == "https://example.org/fallback.pdf"
    assert result.outcome.source == "unpaywall"


@pytest.mark.asyncio
async def test_pipeline_falls_back_to_unpaywall_when_arxiv_is_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_openalex(row, request_email: str | None = None, openalex_api_key: str | None = None):
        _ = (row, request_email, openalex_api_key)
        return None

    async def _raise_rate_limit(row, *, request_email: str | None = None, allow_lookup: bool = True):
        _ = (row, request_email, allow_lookup)
        raise ArxivRateLimitError("arXiv rate limit hit (429) — stopping batch")

    async def _fake_oa(*, row, request_email):
        _ = (row, request_email)
        return _oa_fallback_outcome(pdf_url="https://example.org/fallback.pdf", source="unpaywall")

    monkeypatch.setattr(pipeline, "_openalex_outcome", _fake_openalex)
    monkeypatch.setattr(pipeline, "_arxiv_outcome", _raise_rate_limit)
    monkeypatch.setattr(pipeline, "_oa_outcome", _fake_oa)

    result = await pipeline.resolve_publication_pdf_outcome_for_row(row=_row(), request_email="user@example.com")

    assert result.outcome is not None
    assert result.outcome.source == "unpaywall"
    assert result.arxiv_rate_limited is True


@pytest.mark.asyncio
async def test_arxiv_outcome_skips_when_strong_doi_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row(
        display_identifier=DisplayIdentifier(
            kind="doi",
            value="10.1000/example",
            label="DOI",
            url="https://doi.org/10.1000/example",
            confidence_score=1.0,
        )
    )

    async def _fail_discover(*, item, request_email: str | None = None, timeout_seconds: float | None = None):
        raise AssertionError("arXiv lookup should be skipped when DOI evidence is strong.")

    monkeypatch.setattr(
        "app.services.arxiv.application.discover_arxiv_id_for_publication",
        _fail_discover,
    )
    outcome = await pipeline._arxiv_outcome(row, request_email="user@example.com")
    assert outcome is None


@pytest.mark.asyncio
async def test_arxiv_outcome_skips_when_title_quality_is_low(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _row()
    row.title = "AI 2024"

    async def _fail_discover(*, item, request_email: str | None = None, timeout_seconds: float | None = None):
        raise AssertionError("arXiv lookup should be skipped for low-quality titles.")

    monkeypatch.setattr(
        "app.services.arxiv.application.discover_arxiv_id_for_publication",
        _fail_discover,
    )
    outcome = await pipeline._arxiv_outcome(row, request_email="user@example.com")
    assert outcome is None


@pytest.mark.asyncio
async def test_arxiv_outcome_calls_arxiv_when_eligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_discover(*, item, request_email: str | None = None, timeout_seconds: float | None = None):
        return "1234.5678"

    monkeypatch.setattr(
        "app.services.arxiv.application.discover_arxiv_id_for_publication",
        _fake_discover,
    )
    row = _row()
    row.title = "Reliable Graph Neural Network Benchmark across Multiple Datasets"
    outcome = await pipeline._arxiv_outcome(row, request_email="user@example.com")

    assert outcome is not None
    assert outcome.source == "arxiv"
    assert outcome.pdf_url == "https://arxiv.org/pdf/1234.5678.pdf"
