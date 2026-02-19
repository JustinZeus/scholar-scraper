from __future__ import annotations

import pytest

from app.services.user_settings import (
    DEFAULT_NAV_VISIBLE_PAGES,
    HARD_MIN_REQUEST_DELAY_SECONDS,
    HARD_MIN_RUN_INTERVAL_MINUTES,
    UserSettingsServiceError,
    parse_nav_visible_pages,
    parse_request_delay_seconds,
    parse_run_interval_minutes,
    resolve_request_delay_minimum,
    resolve_run_interval_minimum,
)


def test_parse_run_interval_minutes_accepts_valid_value() -> None:
    assert parse_run_interval_minutes("30") == 30


def test_parse_run_interval_minutes_rejects_below_minimum() -> None:
    with pytest.raises(
        UserSettingsServiceError,
        match="Check interval must be at least 15 minutes.",
    ):
        parse_run_interval_minutes("14")


def test_parse_request_delay_seconds_accepts_valid_value() -> None:
    assert parse_request_delay_seconds("2") == 2


def test_parse_request_delay_seconds_rejects_below_minimum() -> None:
    with pytest.raises(
        UserSettingsServiceError,
        match="Request delay must be at least 2 seconds.",
    ):
        parse_request_delay_seconds("1")


def test_parse_run_interval_minutes_rejects_below_configured_minimum() -> None:
    with pytest.raises(
        UserSettingsServiceError,
        match="Check interval must be at least 30 minutes.",
    ):
        parse_run_interval_minutes("29", minimum=30)


def test_parse_request_delay_seconds_rejects_below_configured_minimum() -> None:
    with pytest.raises(
        UserSettingsServiceError,
        match="Request delay must be at least 8 seconds.",
    ):
        parse_request_delay_seconds("7", minimum=8)


def test_resolve_minimums_keep_hard_floors() -> None:
    assert resolve_run_interval_minimum(1) == HARD_MIN_RUN_INTERVAL_MINUTES
    assert resolve_request_delay_minimum(0) == HARD_MIN_REQUEST_DELAY_SECONDS


def test_parse_nav_visible_pages_accepts_valid_pages() -> None:
    parsed = parse_nav_visible_pages(
        [
            "dashboard",
            "scholars",
            "publications",
            "settings",
            "runs",
        ]
    )
    assert parsed == [
        "dashboard",
        "scholars",
        "publications",
        "settings",
        "runs",
    ]


def test_parse_nav_visible_pages_rejects_missing_required_pages() -> None:
    with pytest.raises(
        UserSettingsServiceError,
        match="Dashboard, Scholars, and Settings must remain visible.",
    ):
        parse_nav_visible_pages(["dashboard", "publications"])


def test_parse_nav_visible_pages_rejects_unknown_page() -> None:
    with pytest.raises(
        UserSettingsServiceError,
        match="Unsupported navigation page id: reports",
    ):
        parse_nav_visible_pages(DEFAULT_NAV_VISIBLE_PAGES + ["reports"])
