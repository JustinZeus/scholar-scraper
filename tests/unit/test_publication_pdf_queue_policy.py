from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db.models import PublicationPdfJob
from app.services.domains.publications import pdf_queue
from app.services.domains.publications.pdf_resolution_pipeline import PipelineOutcome
from app.services.domains.unpaywall.application import OaResolutionOutcome


def _job(
    *,
    status: str,
    attempt_count: int,
    last_attempt_at: datetime | None,
) -> PublicationPdfJob:
    return PublicationPdfJob(
        publication_id=1,
        status=status,
        attempt_count=attempt_count,
        last_attempt_at=last_attempt_at,
    )


def _row(*, pub_url: str | None = "https://scholar.google.com/citations?view_op=view_citation&citation_for_view=abc:xyz") -> SimpleNamespace:
    return SimpleNamespace(
        publication_id=1,
        scholar_profile_id=1,
        scholar_label="Ada Lovelace",
        title="A paper",
        year=2024,
        citation_count=0,
        venue_text=None,
        pub_url=pub_url,
        doi=None,
        pdf_url=None,
        is_read=False,
        is_favorite=False,
        first_seen_at=datetime(2026, 2, 22, 12, 0, tzinfo=timezone.utc),
        is_new_in_latest_run=True,
    )


def test_pdf_queue_auto_enqueue_blocks_recent_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(pdf_queue, "_utcnow", lambda: now)
    monkeypatch.setattr(pdf_queue, "_auto_retry_first_interval_seconds", lambda: 3_600)
    monkeypatch.setattr(pdf_queue, "_auto_retry_interval_seconds", lambda: 86_400)
    monkeypatch.setattr(pdf_queue, "_auto_retry_max_attempts", lambda: 3)
    job = _job(
        status=pdf_queue.PDF_STATUS_FAILED,
        attempt_count=1,
        last_attempt_at=now - timedelta(hours=2),
    )
    assert pdf_queue._can_enqueue_job(job, force_retry=False) is True


def test_pdf_queue_auto_enqueue_blocks_recent_first_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(pdf_queue, "_utcnow", lambda: now)
    monkeypatch.setattr(pdf_queue, "_auto_retry_first_interval_seconds", lambda: 3_600)
    monkeypatch.setattr(pdf_queue, "_auto_retry_interval_seconds", lambda: 86_400)
    monkeypatch.setattr(pdf_queue, "_auto_retry_max_attempts", lambda: 3)
    job = _job(
        status=pdf_queue.PDF_STATUS_FAILED,
        attempt_count=1,
        last_attempt_at=now - timedelta(minutes=20),
    )
    assert pdf_queue._can_enqueue_job(job, force_retry=False) is False


def test_pdf_queue_auto_enqueue_blocks_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(pdf_queue, "_utcnow", lambda: now)
    monkeypatch.setattr(pdf_queue, "_auto_retry_first_interval_seconds", lambda: 3_600)
    monkeypatch.setattr(pdf_queue, "_auto_retry_interval_seconds", lambda: 86_400)
    monkeypatch.setattr(pdf_queue, "_auto_retry_max_attempts", lambda: 3)
    job = _job(
        status=pdf_queue.PDF_STATUS_FAILED,
        attempt_count=3,
        last_attempt_at=now - timedelta(days=2),
    )
    assert pdf_queue._can_enqueue_job(job, force_retry=False) is False


def test_pdf_queue_auto_enqueue_blocks_second_retry_within_day(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(pdf_queue, "_utcnow", lambda: now)
    monkeypatch.setattr(pdf_queue, "_auto_retry_first_interval_seconds", lambda: 3_600)
    monkeypatch.setattr(pdf_queue, "_auto_retry_interval_seconds", lambda: 86_400)
    monkeypatch.setattr(pdf_queue, "_auto_retry_max_attempts", lambda: 3)
    job = _job(
        status=pdf_queue.PDF_STATUS_FAILED,
        attempt_count=2,
        last_attempt_at=now - timedelta(hours=2),
    )
    assert pdf_queue._can_enqueue_job(job, force_retry=False) is False


def test_pdf_queue_manual_requeue_bypasses_cooldown_and_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(pdf_queue, "_utcnow", lambda: now)
    monkeypatch.setattr(pdf_queue, "_auto_retry_first_interval_seconds", lambda: 3_600)
    monkeypatch.setattr(pdf_queue, "_auto_retry_interval_seconds", lambda: 86_400)
    monkeypatch.setattr(pdf_queue, "_auto_retry_max_attempts", lambda: 3)
    job = _job(
        status=pdf_queue.PDF_STATUS_FAILED,
        attempt_count=5,
        last_attempt_at=now - timedelta(minutes=10),
    )
    assert pdf_queue._can_enqueue_job(job, force_retry=True) is True


def test_pdf_queue_manual_requeue_still_blocks_when_inflight() -> None:
    running = _job(
        status=pdf_queue.PDF_STATUS_RUNNING,
        attempt_count=1,
        last_attempt_at=None,
    )
    queued = _job(
        status=pdf_queue.PDF_STATUS_QUEUED,
        attempt_count=1,
        last_attempt_at=None,
    )
    assert pdf_queue._can_enqueue_job(running, force_retry=True) is False
    assert pdf_queue._can_enqueue_job(queued, force_retry=True) is False


@pytest.mark.asyncio
async def test_fetch_outcome_for_row_uses_pipeline_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_pipeline(*, row, request_email=None):
        assert request_email == "user@example.com"
        return PipelineOutcome(
            outcome=OaResolutionOutcome(
                publication_id=row.publication_id,
                doi=None,
                pdf_url="https://arxiv.org/pdf/1703.06103",
                failure_reason=None,
                source=pdf_queue.PDF_SOURCE_SCHOLAR_PUBLICATION_PAGE,
                used_crossref=False,
            ),
            scholar_candidates=None,
        )

    monkeypatch.setattr(pdf_queue, "resolve_publication_pdf_outcome_for_row", _fake_pipeline)

    outcome = await pdf_queue._fetch_outcome_for_row(row=_row(), request_email="user@example.com")

    assert outcome.pdf_url == "https://arxiv.org/pdf/1703.06103"
    assert outcome.source == pdf_queue.PDF_SOURCE_SCHOLAR_PUBLICATION_PAGE
    assert outcome.used_crossref is False


@pytest.mark.asyncio
async def test_fetch_outcome_for_row_returns_failed_outcome_when_pipeline_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_pipeline(*, row, request_email=None):
        assert request_email == "user@example.com"
        return PipelineOutcome(outcome=None, scholar_candidates=None)

    monkeypatch.setattr(pdf_queue, "resolve_publication_pdf_outcome_for_row", _fake_pipeline)

    outcome = await pdf_queue._fetch_outcome_for_row(row=_row(), request_email="user@example.com")

    assert outcome.pdf_url is None
    assert outcome.failure_reason == pdf_queue.FAILURE_RESOLUTION_EXCEPTION
