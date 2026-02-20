from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import UserSetting
from app.services.domains.ingestion import safety as run_safety


def test_apply_run_safety_outcome_triggers_blocked_cooldown() -> None:
    settings = UserSetting(user_id=1, scrape_safety_state={})
    now = datetime(2026, 2, 19, 20, 0, tzinfo=timezone.utc)

    safety_state, reason = run_safety.apply_run_safety_outcome(
        settings,
        run_id=12,
        blocked_failure_count=2,
        network_failure_count=0,
        blocked_failure_threshold=1,
        network_failure_threshold=2,
        blocked_cooldown_seconds=600,
        network_cooldown_seconds=300,
        now_utc=now,
    )

    assert reason == run_safety.COOLDOWN_REASON_BLOCKED_FAILURE_THRESHOLD
    assert safety_state["cooldown_active"] is True
    assert safety_state["cooldown_reason"] == run_safety.COOLDOWN_REASON_BLOCKED_FAILURE_THRESHOLD
    assert safety_state["cooldown_remaining_seconds"] == 600
    assert safety_state["counters"]["cooldown_entry_count"] == 1
    assert safety_state["counters"]["last_blocked_failure_count"] == 2
    assert safety_state["counters"]["last_evaluated_run_id"] == 12


def test_clear_expired_cooldown() -> None:
    now = datetime(2026, 2, 19, 20, 0, tzinfo=timezone.utc)
    settings = UserSetting(
        user_id=1,
        scrape_safety_state={"blocked_start_count": 3},
        scrape_cooldown_until=now - timedelta(seconds=5),
        scrape_cooldown_reason=run_safety.COOLDOWN_REASON_NETWORK_FAILURE_THRESHOLD,
    )

    changed = run_safety.clear_expired_cooldown(settings, now_utc=now)
    safety_state = run_safety.get_safety_state_payload(settings, now_utc=now)

    assert changed is True
    assert safety_state["cooldown_active"] is False
    assert safety_state["cooldown_reason"] is None
    assert safety_state["counters"]["blocked_start_count"] == 3


def test_apply_run_safety_outcome_triggers_network_cooldown() -> None:
    settings = UserSetting(user_id=1, scrape_safety_state={})
    now = datetime(2026, 2, 19, 20, 0, tzinfo=timezone.utc)

    safety_state, reason = run_safety.apply_run_safety_outcome(
        settings,
        run_id=21,
        blocked_failure_count=0,
        network_failure_count=3,
        blocked_failure_threshold=2,
        network_failure_threshold=1,
        blocked_cooldown_seconds=900,
        network_cooldown_seconds=300,
        now_utc=now,
    )

    assert reason == run_safety.COOLDOWN_REASON_NETWORK_FAILURE_THRESHOLD
    assert safety_state["cooldown_active"] is True
    assert safety_state["cooldown_reason"] == run_safety.COOLDOWN_REASON_NETWORK_FAILURE_THRESHOLD
    assert safety_state["cooldown_remaining_seconds"] == 300
    assert safety_state["counters"]["cooldown_entry_count"] == 1
    assert safety_state["counters"]["last_network_failure_count"] == 3
    assert safety_state["counters"]["last_evaluated_run_id"] == 21


def test_register_cooldown_blocked_start_increments_counter() -> None:
    now = datetime(2026, 2, 19, 20, 0, tzinfo=timezone.utc)
    settings = UserSetting(
        user_id=1,
        scrape_safety_state={"blocked_start_count": 1},
        scrape_cooldown_until=now + timedelta(minutes=5),
        scrape_cooldown_reason=run_safety.COOLDOWN_REASON_BLOCKED_FAILURE_THRESHOLD,
    )

    safety_state = run_safety.register_cooldown_blocked_start(settings, now_utc=now)

    assert safety_state["cooldown_active"] is True
    assert safety_state["cooldown_reason"] == run_safety.COOLDOWN_REASON_BLOCKED_FAILURE_THRESHOLD
    assert safety_state["counters"]["blocked_start_count"] == 2


def test_get_safety_event_context_contains_structured_fields() -> None:
    now = datetime(2026, 2, 19, 20, 0, tzinfo=timezone.utc)
    settings = UserSetting(
        user_id=1,
        scrape_safety_state={"cooldown_entry_count": 4},
        scrape_cooldown_until=now + timedelta(minutes=10),
        scrape_cooldown_reason=run_safety.COOLDOWN_REASON_BLOCKED_FAILURE_THRESHOLD,
    )

    event_context = run_safety.get_safety_event_context(settings, now_utc=now)

    assert event_context["cooldown_active"] is True
    assert event_context["cooldown_reason"] == run_safety.COOLDOWN_REASON_BLOCKED_FAILURE_THRESHOLD
    assert int(event_context["cooldown_remaining_seconds"]) == 600
    assert event_context["safety_counters"]["cooldown_entry_count"] == 4
