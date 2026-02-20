from __future__ import annotations

from typing import Any


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _summary_dict(error_log: object) -> dict[str, Any]:
    if not isinstance(error_log, dict):
        return {}
    summary = error_log.get("summary")
    if not isinstance(summary, dict):
        return {}
    return summary


def _summary_int_dict(summary: dict[str, Any], key: str) -> dict[str, int]:
    value = summary.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        str(item_key): _safe_int(item_value, 0)
        for item_key, item_value in value.items()
        if isinstance(item_key, str)
    }


def _summary_bool_dict(summary: dict[str, Any], key: str) -> dict[str, bool]:
    value = summary.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        str(item_key): bool(item_value)
        for item_key, item_value in value.items()
        if isinstance(item_key, str)
    }


def _retry_counts(summary: dict[str, Any]) -> dict[str, int]:
    retry_counts = summary.get("retry_counts")
    if not isinstance(retry_counts, dict):
        retry_counts = {}
    return {
        "retries_scheduled_count": _safe_int(
            retry_counts.get("retries_scheduled_count", 0),
            0,
        ),
        "scholars_with_retries_count": _safe_int(
            retry_counts.get("scholars_with_retries_count", 0),
            0,
        ),
        "retry_exhausted_count": _safe_int(
            retry_counts.get("retry_exhausted_count", 0),
            0,
        ),
    }


def extract_run_summary(error_log: object) -> dict[str, Any]:
    summary = _summary_dict(error_log)
    return {
        "succeeded_count": _safe_int(summary.get("succeeded_count", 0)),
        "failed_count": _safe_int(summary.get("failed_count", 0)),
        "partial_count": _safe_int(summary.get("partial_count", 0)),
        "failed_state_counts": _summary_int_dict(summary, "failed_state_counts"),
        "failed_reason_counts": _summary_int_dict(summary, "failed_reason_counts"),
        "scrape_failure_counts": _summary_int_dict(summary, "scrape_failure_counts"),
        "retry_counts": _retry_counts(summary),
        "alert_thresholds": _summary_int_dict(summary, "alert_thresholds"),
        "alert_flags": _summary_bool_dict(summary, "alert_flags"),
    }
