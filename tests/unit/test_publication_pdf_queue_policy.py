from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.db.models import PublicationPdfJob
from app.services.publications import pdf_queue, pdf_queue_resolution
from app.services.publications.pdf_resolution_pipeline import PipelineOutcome
from app.services.unpaywall.application import OaResolutionOutcome


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


def _row(
    *, pub_url: str | None = "https://scholar.google.com/citations?view_op=view_citation&citation_for_view=abc:xyz"
) -> Any:
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
        first_seen_at=datetime(2026, 2, 22, 12, 0, tzinfo=UTC),
        is_new_in_latest_run=True,
    )


def test_pdf_queue_auto_enqueue_blocks_recent_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 2, 21, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(pdf_queue, "utcnow", lambda: now)
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
    now = datetime(2026, 2, 21, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(pdf_queue, "utcnow", lambda: now)
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
    now = datetime(2026, 2, 21, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(pdf_queue, "utcnow", lambda: now)
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
    now = datetime(2026, 2, 21, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(pdf_queue, "utcnow", lambda: now)
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
    now = datetime(2026, 2, 21, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(pdf_queue, "utcnow", lambda: now)
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
    async def _fake_pipeline(*, row, request_email=None, openalex_api_key=None, allow_arxiv_lookup=True):
        assert request_email == "user@example.com"
        assert allow_arxiv_lookup is True
        return PipelineOutcome(
            outcome=OaResolutionOutcome(
                publication_id=row.publication_id,
                doi=None,
                pdf_url="https://arxiv.org/pdf/1703.06103",
                failure_reason=None,
                source="openalex",
                used_crossref=False,
            ),
            scholar_candidates=None,
        )

    monkeypatch.setattr(pdf_queue_resolution, "resolve_publication_pdf_outcome_for_row", _fake_pipeline)

    outcome, arxiv_rate_limited = await pdf_queue_resolution._fetch_outcome_for_row(
        row=_row(),
        request_email="user@example.com",
    )

    assert outcome.pdf_url == "https://arxiv.org/pdf/1703.06103"
    assert outcome.source == "openalex"
    assert outcome.used_crossref is False
    assert arxiv_rate_limited is False


@pytest.mark.asyncio
async def test_fetch_outcome_for_row_returns_failed_outcome_when_pipeline_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_pipeline(*, row, request_email=None, openalex_api_key=None, allow_arxiv_lookup=True):
        assert request_email == "user@example.com"
        assert allow_arxiv_lookup is True
        return PipelineOutcome(outcome=None, scholar_candidates=None, arxiv_rate_limited=True)

    monkeypatch.setattr(pdf_queue_resolution, "resolve_publication_pdf_outcome_for_row", _fake_pipeline)

    outcome, arxiv_rate_limited = await pdf_queue_resolution._fetch_outcome_for_row(
        row=_row(),
        request_email="user@example.com",
    )

    assert outcome.pdf_url is None
    assert outcome.failure_reason == pdf_queue_resolution.FAILURE_RESOLUTION_EXCEPTION
    assert arxiv_rate_limited is True


@pytest.mark.asyncio
async def test_resolve_publication_row_persists_outcome_and_returns_rate_limit_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[int, int, OaResolutionOutcome]] = []

    async def _noop_mark_attempt_started(*, publication_id: int, user_id: int) -> None:
        return None

    async def _fake_fetch(*, row, request_email=None, openalex_api_key=None, allow_arxiv_lookup=True):
        assert allow_arxiv_lookup is True
        return (
            OaResolutionOutcome(
                publication_id=row.publication_id,
                doi=None,
                pdf_url="https://fallback.example/test.pdf",
                failure_reason=None,
                source="unpaywall",
                used_crossref=False,
            ),
            True,
        )

    async def _capture_persist_outcome(*, publication_id: int, user_id: int, outcome: OaResolutionOutcome) -> None:
        captured.append((publication_id, user_id, outcome))

    monkeypatch.setattr(pdf_queue_resolution, "_mark_attempt_started", _noop_mark_attempt_started)
    monkeypatch.setattr(pdf_queue_resolution, "_fetch_outcome_for_row", _fake_fetch)
    monkeypatch.setattr(pdf_queue_resolution, "_persist_outcome", _capture_persist_outcome)

    rate_limited = await pdf_queue_resolution._resolve_publication_row(
        user_id=42,
        request_email="user@example.com",
        row=_row(),
        openalex_api_key="key",
    )

    assert len(captured) == 1
    publication_id, user_id, outcome = captured[0]
    assert publication_id == 1
    assert user_id == 42
    assert outcome.pdf_url == "https://fallback.example/test.pdf"
    assert rate_limited is True


@pytest.mark.asyncio
async def test_run_resolution_task_disables_arxiv_for_remaining_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, bool]] = []
    first = _row()
    second: Any = SimpleNamespace(**{**first.__dict__, "publication_id": 2})

    def _raise_session_factory_error():
        raise RuntimeError("skip user settings lookup in test")

    async def _fake_resolve_publication_row(
        *,
        user_id: int,
        request_email: str | None,
        row,
        openalex_api_key=None,
        allow_arxiv_lookup=True,
    ):
        _ = (user_id, request_email, openalex_api_key)
        calls.append((int(row.publication_id), bool(allow_arxiv_lookup)))
        return row.publication_id == 1

    monkeypatch.setattr(pdf_queue_resolution, "get_session_factory", _raise_session_factory_error)
    monkeypatch.setattr(pdf_queue_resolution, "_resolve_publication_row", _fake_resolve_publication_row)

    await pdf_queue_resolution._run_resolution_task(
        user_id=42,
        request_email="user@example.com",
        rows=[first, second],
    )

    assert calls == [(1, True), (2, False)]
