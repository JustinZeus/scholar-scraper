from __future__ import annotations

from app.services.domains.runs.application import extract_run_summary


def test_extract_run_summary_includes_extended_metrics() -> None:
    error_log = {
        "summary": {
            "succeeded_count": 3,
            "failed_count": 1,
            "partial_count": 2,
            "failed_state_counts": {"network_error": 1},
            "failed_reason_counts": {"network_timeout": 1},
            "scrape_failure_counts": {"network_error": 1},
            "retry_counts": {
                "retries_scheduled_count": 4,
                "scholars_with_retries_count": 2,
                "retry_exhausted_count": 1,
            },
            "alert_thresholds": {
                "blocked_failure_threshold": 1,
                "network_failure_threshold": 2,
                "retry_scheduled_threshold": 3,
            },
            "alert_flags": {
                "blocked_failure_threshold_exceeded": False,
                "network_failure_threshold_exceeded": True,
                "retry_scheduled_threshold_exceeded": True,
            },
        }
    }

    summary = extract_run_summary(error_log)

    assert summary["succeeded_count"] == 3
    assert summary["failed_count"] == 1
    assert summary["partial_count"] == 2
    assert summary["failed_state_counts"] == {"network_error": 1}
    assert summary["failed_reason_counts"] == {"network_timeout": 1}
    assert summary["scrape_failure_counts"] == {"network_error": 1}
    assert summary["retry_counts"]["retries_scheduled_count"] == 4
    assert summary["retry_counts"]["scholars_with_retries_count"] == 2
    assert summary["retry_counts"]["retry_exhausted_count"] == 1
    assert summary["alert_thresholds"]["retry_scheduled_threshold"] == 3
    assert summary["alert_flags"]["network_failure_threshold_exceeded"] is True


def test_extract_run_summary_defaults_extended_metrics() -> None:
    summary = extract_run_summary({})

    assert summary["scrape_failure_counts"] == {}
    assert summary["retry_counts"] == {
        "retries_scheduled_count": 0,
        "scholars_with_retries_count": 0,
        "retry_exhausted_count": 0,
    }
    assert summary["alert_thresholds"] == {}
    assert summary["alert_flags"] == {}
