from __future__ import annotations

import pytest

from app.services.user_settings import (
    DEFAULT_NAV_VISIBLE_PAGES,
    UserSettingsServiceError,
    parse_nav_visible_pages,
    parse_request_delay_seconds,
    parse_run_interval_minutes,
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
