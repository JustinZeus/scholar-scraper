from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.domains.publications import pdf_resolution_pipeline as pipeline
from app.services.domains.unpaywall.application import OaResolutionOutcome


@dataclass(frozen=True)
class _Candidate:
    url: str
    confidence_score: float
    label_present: bool
    reason: str


@dataclass(frozen=True)
class _Candidates:
    container_seen: bool
    labeled_candidate: _Candidate | None
    fallback_candidate: _Candidate | None
    warnings: tuple[str, ...] = ()


def _row(*, doi: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        publication_id=1,
        scholar_profile_id=1,
        scholar_label="Ada Lovelace",
        title="A paper",
        year=2024,
        citation_count=0,
        venue_text=None,
        pub_url="https://scholar.google.com/citations?view_op=view_citation&citation_for_view=abc:xyz",
        doi=doi,
        pdf_url=None,
        is_read=False,
        is_favorite=False,
        first_seen_at=datetime(2026, 2, 22, 12, 0, tzinfo=timezone.utc),
        is_new_in_latest_run=True,
    )


def _oa_outcome(*, pdf_url: str | None, source: str = "unpaywall") -> OaResolutionOutcome:
    return OaResolutionOutcome(
        publication_id=1,
        doi="10.1000/example",
        pdf_url=pdf_url,
        failure_reason=None if pdf_url else "no_pdf_found",
        source=source,
        used_crossref=False,
    )


@pytest.mark.asyncio
async def test_pipeline_prefers_labeled_scholar_candidate_before_oa(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_candidates(_url):
        return _Candidates(
            container_seen=True,
            labeled_candidate=_Candidate(
                url="https://arxiv.org/pdf/1703.06103",
                confidence_score=0.98,
                label_present=True,
                reason="scholar_link_labeled_pdf",
            ),
            fallback_candidate=None,
        )

    async def _fail_oa(*, row, request_email):
        raise AssertionError(f"OA should not run when labeled Scholar candidate exists: {row.publication_id} {request_email}")

    monkeypatch.setattr(pipeline, "fetch_link_candidates_from_scholar_publication_page", _fake_candidates)
    monkeypatch.setattr(pipeline, "_oa_outcome", _fail_oa)

    result = await pipeline.resolve_publication_pdf_outcome_for_row(row=_row(), request_email="user@example.com")

    assert result.outcome is not None
    assert result.outcome.pdf_url == "https://arxiv.org/pdf/1703.06103"
    assert result.outcome.source == pipeline.PDF_SOURCE_SCHOLAR_PUBLICATION_PAGE


@pytest.mark.asyncio
async def test_pipeline_uses_oa_result_before_unlabeled_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_candidates(_url):
        return _Candidates(
            container_seen=True,
            labeled_candidate=None,
            fallback_candidate=_Candidate(
                url="https://example.org/download/42",
                confidence_score=0.2,
                label_present=False,
                reason="scholar_link_unlabeled_fallback",
            ),
        )

    async def _fake_oa(*, row, request_email):
        assert request_email == "user@example.com"
        return _oa_outcome(pdf_url="https://oa.example.org/found.pdf")

    async def _fail_fallback(*, row, candidate):
        raise AssertionError(f"Unlabeled fallback should not run when OA returns PDF: {row.publication_id} {candidate.url}")

    monkeypatch.setattr(pipeline, "fetch_link_candidates_from_scholar_publication_page", _fake_candidates)
    monkeypatch.setattr(pipeline, "_oa_outcome", _fake_oa)
    monkeypatch.setattr(pipeline, "_unlabeled_fallback_outcome", _fail_fallback)

    result = await pipeline.resolve_publication_pdf_outcome_for_row(row=_row(), request_email="user@example.com")

    assert result.outcome is not None
    assert result.outcome.pdf_url == "https://oa.example.org/found.pdf"
    assert result.outcome.source == "unpaywall"


@pytest.mark.asyncio
async def test_pipeline_uses_unlabeled_fallback_after_oa_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback_candidate = _Candidate(
        url="https://example.org/download/42",
        confidence_score=0.2,
        label_present=False,
        reason="scholar_link_unlabeled_fallback",
    )

    async def _fake_candidates(_url):
        return _Candidates(container_seen=True, labeled_candidate=None, fallback_candidate=fallback_candidate)

    async def _fake_oa(*, row, request_email):
        assert request_email == "user@example.com"
        return _oa_outcome(pdf_url=None)

    async def _fake_fallback(*, row, candidate):
        assert candidate == fallback_candidate
        return OaResolutionOutcome(
            publication_id=row.publication_id,
            doi=row.doi,
            pdf_url="https://example.org/fallback.pdf",
            failure_reason=None,
            source=pipeline.PDF_SOURCE_SCHOLAR_PUBLICATION_PAGE_UNLABELED,
            used_crossref=False,
        )

    monkeypatch.setattr(pipeline, "fetch_link_candidates_from_scholar_publication_page", _fake_candidates)
    monkeypatch.setattr(pipeline, "_oa_outcome", _fake_oa)
    monkeypatch.setattr(pipeline, "_unlabeled_fallback_outcome", _fake_fallback)

    result = await pipeline.resolve_publication_pdf_outcome_for_row(row=_row(), request_email="user@example.com")

    assert result.outcome is not None
    assert result.outcome.pdf_url == "https://example.org/fallback.pdf"
    assert result.outcome.source == pipeline.PDF_SOURCE_SCHOLAR_PUBLICATION_PAGE_UNLABELED
