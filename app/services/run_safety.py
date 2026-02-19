from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.models import UserSetting

COOLDOWN_REASON_BLOCKED_FAILURE_THRESHOLD = "blocked_failure_threshold_exceeded"
COOLDOWN_REASON_NETWORK_FAILURE_THRESHOLD = "network_failure_threshold_exceeded"

_COUNTER_CONSECUTIVE_BLOCKED_RUNS = "consecutive_blocked_runs"
_COUNTER_CONSECUTIVE_NETWORK_RUNS = "consecutive_network_runs"
_COUNTER_COOLDOWN_ENTRY_COUNT = "cooldown_entry_count"
_COUNTER_BLOCKED_START_COUNT = "blocked_start_count"
_COUNTER_LAST_BLOCKED_FAILURE_COUNT = "last_blocked_failure_count"
_COUNTER_LAST_NETWORK_FAILURE_COUNT = "last_network_failure_count"
_COUNTER_LAST_EVALUATED_RUN_ID = "last_evaluated_run_id"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _state_dict(settings: UserSetting) -> dict[str, Any]:
    state = settings.scrape_safety_state
    if isinstance(state, dict):
        return state
    return {}


def _counters_from_state(settings: UserSetting) -> dict[str, Any]:
    state = _state_dict(settings)
    return {
        _COUNTER_CONSECUTIVE_BLOCKED_RUNS: max(
            0,
            _safe_int(state.get(_COUNTER_CONSECUTIVE_BLOCKED_RUNS), 0),
        ),
        _COUNTER_CONSECUTIVE_NETWORK_RUNS: max(
            0,
            _safe_int(state.get(_COUNTER_CONSECUTIVE_NETWORK_RUNS), 0),
        ),
        _COUNTER_COOLDOWN_ENTRY_COUNT: max(
            0,
            _safe_int(state.get(_COUNTER_COOLDOWN_ENTRY_COUNT), 0),
        ),
        _COUNTER_BLOCKED_START_COUNT: max(
            0,
            _safe_int(state.get(_COUNTER_BLOCKED_START_COUNT), 0),
        ),
        _COUNTER_LAST_BLOCKED_FAILURE_COUNT: max(
            0,
            _safe_int(state.get(_COUNTER_LAST_BLOCKED_FAILURE_COUNT), 0),
        ),
        _COUNTER_LAST_NETWORK_FAILURE_COUNT: max(
            0,
            _safe_int(state.get(_COUNTER_LAST_NETWORK_FAILURE_COUNT), 0),
        ),
        _COUNTER_LAST_EVALUATED_RUN_ID: _safe_optional_int(
            state.get(_COUNTER_LAST_EVALUATED_RUN_ID),
        ),
    }


def _cooldown_reason_label(reason: str | None) -> str | None:
    if reason == COOLDOWN_REASON_BLOCKED_FAILURE_THRESHOLD:
        return "Blocked responses exceeded safety threshold"
    if reason == COOLDOWN_REASON_NETWORK_FAILURE_THRESHOLD:
        return "Network failures exceeded safety threshold"
    return None


def _recommended_action(reason: str | None) -> str | None:
    if reason == COOLDOWN_REASON_BLOCKED_FAILURE_THRESHOLD:
        return (
            "Google Scholar appears to be blocking requests. Wait for cooldown to expire, "
            "increase request delay, and avoid repeated manual retries."
        )
    if reason == COOLDOWN_REASON_NETWORK_FAILURE_THRESHOLD:
        return (
            "Network failures crossed the threshold. Verify connectivity and retry after cooldown."
        )
    return None


def is_cooldown_active(
    settings: UserSetting,
    *,
    now_utc: datetime | None = None,
) -> bool:
    now = now_utc or _utcnow()
    cooldown_until = _normalize_datetime(settings.scrape_cooldown_until)
    if cooldown_until is None:
        return False
    return cooldown_until > now


def clear_expired_cooldown(
    settings: UserSetting,
    *,
    now_utc: datetime | None = None,
) -> bool:
    now = now_utc or _utcnow()
    cooldown_until = _normalize_datetime(settings.scrape_cooldown_until)
    if cooldown_until is None:
        return False
    if cooldown_until > now:
        return False
    settings.scrape_cooldown_until = None
    settings.scrape_cooldown_reason = None
    return True


def register_cooldown_blocked_start(
    settings: UserSetting,
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    now = now_utc or _utcnow()
    counters = _counters_from_state(settings)
    counters[_COUNTER_BLOCKED_START_COUNT] = int(counters[_COUNTER_BLOCKED_START_COUNT]) + 1
    settings.scrape_safety_state = counters
    return get_safety_state_payload(settings, now_utc=now)


def _update_run_counters(
    *,
    counters: dict[str, Any],
    run_id: int,
    blocked_failure_count: int,
    network_failure_count: int,
) -> tuple[int, int]:
    bounded_blocked_failures = max(0, int(blocked_failure_count))
    bounded_network_failures = max(0, int(network_failure_count))
    counters[_COUNTER_LAST_BLOCKED_FAILURE_COUNT] = bounded_blocked_failures
    counters[_COUNTER_LAST_NETWORK_FAILURE_COUNT] = bounded_network_failures
    counters[_COUNTER_LAST_EVALUATED_RUN_ID] = int(run_id)
    counters[_COUNTER_CONSECUTIVE_BLOCKED_RUNS] = (
        int(counters[_COUNTER_CONSECUTIVE_BLOCKED_RUNS]) + 1
        if bounded_blocked_failures > 0
        else 0
    )
    counters[_COUNTER_CONSECUTIVE_NETWORK_RUNS] = (
        int(counters[_COUNTER_CONSECUTIVE_NETWORK_RUNS]) + 1
        if bounded_network_failures > 0
        else 0
    )
    return bounded_blocked_failures, bounded_network_failures


def _resolve_cooldown_trigger(
    *,
    blocked_failures: int,
    network_failures: int,
    blocked_failure_threshold: int,
    network_failure_threshold: int,
    blocked_cooldown_seconds: int,
    network_cooldown_seconds: int,
) -> tuple[str | None, int]:
    if blocked_failures >= max(1, int(blocked_failure_threshold)):
        return COOLDOWN_REASON_BLOCKED_FAILURE_THRESHOLD, max(60, int(blocked_cooldown_seconds))
    if network_failures >= max(1, int(network_failure_threshold)):
        return COOLDOWN_REASON_NETWORK_FAILURE_THRESHOLD, max(60, int(network_cooldown_seconds))
    return None, 0


def _apply_cooldown_decision(
    *,
    settings: UserSetting,
    counters: dict[str, Any],
    now: datetime,
    reason: str | None,
    cooldown_seconds: int,
) -> None:
    if reason is None:
        clear_expired_cooldown(settings, now_utc=now)
        return
    settings.scrape_cooldown_reason = reason
    settings.scrape_cooldown_until = now + timedelta(seconds=max(60, int(cooldown_seconds)))
    counters[_COUNTER_COOLDOWN_ENTRY_COUNT] = int(counters[_COUNTER_COOLDOWN_ENTRY_COUNT]) + 1


def apply_run_safety_outcome(
    settings: UserSetting,
    *,
    run_id: int,
    blocked_failure_count: int,
    network_failure_count: int,
    blocked_failure_threshold: int,
    network_failure_threshold: int,
    blocked_cooldown_seconds: int,
    network_cooldown_seconds: int,
    now_utc: datetime | None = None,
) -> tuple[dict[str, Any], str | None]:
    now = now_utc or _utcnow()
    counters = _counters_from_state(settings)
    blocked_failures, network_failures = _update_run_counters(
        counters=counters,
        run_id=run_id,
        blocked_failure_count=blocked_failure_count,
        network_failure_count=network_failure_count,
    )
    reason, cooldown_seconds = _resolve_cooldown_trigger(
        blocked_failures=blocked_failures,
        network_failures=network_failures,
        blocked_failure_threshold=blocked_failure_threshold,
        network_failure_threshold=network_failure_threshold,
        blocked_cooldown_seconds=blocked_cooldown_seconds,
        network_cooldown_seconds=network_cooldown_seconds,
    )
    _apply_cooldown_decision(
        settings=settings,
        counters=counters,
        now=now,
        reason=reason,
        cooldown_seconds=cooldown_seconds,
    )
    settings.scrape_safety_state = counters
    return get_safety_state_payload(settings, now_utc=now), reason


def get_safety_state_payload(
    settings: UserSetting,
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    now = now_utc or _utcnow()
    cooldown_until = _normalize_datetime(settings.scrape_cooldown_until)
    cooldown_active = bool(cooldown_until is not None and cooldown_until > now)
    cooldown_remaining_seconds = 0
    if cooldown_active and cooldown_until is not None:
        cooldown_remaining_seconds = max(0, int((cooldown_until - now).total_seconds()))

    reason = settings.scrape_cooldown_reason if cooldown_active else None

    return {
        "cooldown_active": cooldown_active,
        "cooldown_reason": reason,
        "cooldown_reason_label": _cooldown_reason_label(reason),
        "cooldown_until": cooldown_until,
        "cooldown_remaining_seconds": cooldown_remaining_seconds,
        "recommended_action": _recommended_action(reason),
        "counters": _counters_from_state(settings),
    }


def get_safety_event_context(
    settings: UserSetting,
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    payload = get_safety_state_payload(settings, now_utc=now_utc)
    return {
        "cooldown_active": bool(payload.get("cooldown_active")),
        "cooldown_reason": payload.get("cooldown_reason"),
        "cooldown_until": payload.get("cooldown_until"),
        "cooldown_remaining_seconds": int(payload.get("cooldown_remaining_seconds") or 0),
        "safety_counters": payload.get("counters", {}),
    }
