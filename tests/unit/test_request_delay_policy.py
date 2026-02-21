from __future__ import annotations

from datetime import datetime, timezone

from app.services.domains.ingestion.application import ScholarIngestionService
from app.services.domains.ingestion import scheduler as scheduler_module
from app.settings import settings


def _set_policy_minimum(value: int) -> int:
    previous = int(settings.ingestion_min_request_delay_seconds)
    object.__setattr__(settings, "ingestion_min_request_delay_seconds", int(value))
    return previous


def test_ingestion_effective_request_delay_respects_policy_minimum() -> None:
    previous = _set_policy_minimum(8)
    try:
        assert ScholarIngestionService._effective_request_delay_seconds(7) == 8
        assert ScholarIngestionService._effective_request_delay_seconds(12) == 12
    finally:
        object.__setattr__(settings, "ingestion_min_request_delay_seconds", previous)


def test_scheduler_effective_request_delay_respects_policy_minimum() -> None:
    previous = _set_policy_minimum(9)
    try:
        assert scheduler_module._effective_request_delay_seconds(None) == 9
        assert scheduler_module._effective_request_delay_seconds(6) == 9
        assert scheduler_module._effective_request_delay_seconds(11) == 11
    finally:
        object.__setattr__(settings, "ingestion_min_request_delay_seconds", previous)


def test_scheduler_candidate_row_clamps_request_delay() -> None:
    previous = _set_policy_minimum(6)
    try:
        candidate = scheduler_module.SchedulerService._candidate_from_row(
            (1, 15, 1, None, None),
            now_utc=datetime(2026, 2, 21, tzinfo=timezone.utc),
        )
        assert candidate is not None
        assert candidate.request_delay_seconds == 6
    finally:
        object.__setattr__(settings, "ingestion_min_request_delay_seconds", previous)
