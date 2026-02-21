from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import PublicationPdfJob
from app.services.domains.publications import pdf_queue


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
