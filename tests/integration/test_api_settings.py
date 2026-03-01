from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.services.settings import application as user_settings_service
from app.settings import settings
from tests.integration.helpers import (
    api_csrf_headers,
    assert_safety_state_contract,
    insert_user,
    login_user,
)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_settings_get_and_update(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="api-settings@example.com",
        password="api-password",
    )

    client = TestClient(app)
    login_user(client, email="api-settings@example.com", password="api-password")
    headers = api_csrf_headers(client)

    get_response = client.get("/api/v1/settings")
    assert get_response.status_code == 200
    settings_payload = get_response.json()["data"]
    assert "request_delay_seconds" in settings_payload
    assert "nav_visible_pages" in settings_payload
    assert settings_payload["policy"]["min_run_interval_minutes"] == user_settings_service.resolve_run_interval_minimum(
        settings.ingestion_min_run_interval_minutes
    )
    assert settings_payload["policy"][
        "min_request_delay_seconds"
    ] == user_settings_service.resolve_request_delay_minimum(settings.ingestion_min_request_delay_seconds)
    assert settings_payload["policy"]["automation_allowed"] is settings.ingestion_automation_allowed
    assert settings_payload["policy"]["manual_run_allowed"] is settings.ingestion_manual_run_allowed
    assert settings_payload["policy"]["blocked_failure_threshold"] == max(
        1,
        int(settings.ingestion_alert_blocked_failure_threshold),
    )
    assert settings_payload["policy"]["network_failure_threshold"] == max(
        1,
        int(settings.ingestion_alert_network_failure_threshold),
    )
    assert settings_payload["policy"]["cooldown_blocked_seconds"] == max(
        60,
        int(settings.ingestion_safety_cooldown_blocked_seconds),
    )
    assert settings_payload["policy"]["cooldown_network_seconds"] == max(
        60,
        int(settings.ingestion_safety_cooldown_network_seconds),
    )
    assert_safety_state_contract(settings_payload["safety_state"])
    assert settings_payload["safety_state"]["cooldown_active"] is False

    policy = settings_payload["policy"]
    run_interval_minutes = max(45, int(policy["min_run_interval_minutes"]))
    request_delay_seconds = max(6, int(policy["min_request_delay_seconds"]))

    update_response = client.put(
        "/api/v1/settings",
        json={
            "auto_run_enabled": True,
            "run_interval_minutes": run_interval_minutes,
            "request_delay_seconds": request_delay_seconds,
            "nav_visible_pages": ["dashboard", "scholars", "publications", "settings", "runs"],
        },
        headers=headers,
    )
    assert update_response.status_code == 200
    updated = update_response.json()["data"]
    assert updated["auto_run_enabled"] is True
    assert updated["run_interval_minutes"] == run_interval_minutes
    assert updated["request_delay_seconds"] == request_delay_seconds
    assert updated["nav_visible_pages"] == [
        "dashboard",
        "scholars",
        "publications",
        "settings",
        "runs",
    ]
    assert "policy" in updated
    assert_safety_state_contract(updated["safety_state"])


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_settings_enforce_env_minimums(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="api-settings-policy@example.com",
        password="api-password",
    )

    client = TestClient(app)
    login_user(client, email="api-settings-policy@example.com", password="api-password")
    headers = api_csrf_headers(client)

    previous_min_interval = settings.ingestion_min_run_interval_minutes
    previous_min_delay = settings.ingestion_min_request_delay_seconds
    object.__setattr__(settings, "ingestion_min_run_interval_minutes", 30)
    object.__setattr__(settings, "ingestion_min_request_delay_seconds", 8)
    try:
        interval_response = client.put(
            "/api/v1/settings",
            json={
                "auto_run_enabled": True,
                "run_interval_minutes": 29,
                "request_delay_seconds": 9,
                "nav_visible_pages": ["dashboard", "scholars", "settings"],
            },
            headers=headers,
        )
        assert interval_response.status_code == 400
        assert interval_response.json()["error"]["code"] == "invalid_settings"
        assert interval_response.json()["error"]["message"] == "Check interval must be at least 30 minutes."

        delay_response = client.put(
            "/api/v1/settings",
            json={
                "auto_run_enabled": True,
                "run_interval_minutes": 30,
                "request_delay_seconds": 7,
                "nav_visible_pages": ["dashboard", "scholars", "settings"],
            },
            headers=headers,
        )
        assert delay_response.status_code == 400
        assert delay_response.json()["error"]["code"] == "invalid_settings"
        assert delay_response.json()["error"]["message"] == "Request delay must be at least 8 seconds."
    finally:
        object.__setattr__(settings, "ingestion_min_run_interval_minutes", previous_min_interval)
        object.__setattr__(settings, "ingestion_min_request_delay_seconds", previous_min_delay)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_settings_clears_expired_scrape_safety_cooldown(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-settings-safety-expired@example.com",
        password="api-password",
    )
    user_settings = await user_settings_service.get_or_create_settings(
        db_session,
        user_id=user_id,
    )
    user_settings.scrape_safety_state = {"blocked_start_count": 2}
    user_settings.scrape_cooldown_reason = "blocked_failure_threshold_exceeded"
    user_settings.scrape_cooldown_until = datetime.now(UTC) - timedelta(seconds=15)
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="api-settings-safety-expired@example.com", password="api-password")

    settings_response = client.get("/api/v1/settings")
    assert settings_response.status_code == 200
    settings_safety_state = settings_response.json()["data"]["safety_state"]
    assert_safety_state_contract(settings_safety_state)
    assert settings_safety_state["cooldown_active"] is False
    assert settings_safety_state["cooldown_reason"] is None
    assert int(settings_safety_state["counters"]["blocked_start_count"]) == 2

    runs_response = client.get("/api/v1/runs")
    assert runs_response.status_code == 200
    runs_safety_state = runs_response.json()["data"]["safety_state"]
    assert_safety_state_contract(runs_safety_state)
    assert runs_safety_state["cooldown_active"] is False
    assert runs_safety_state["cooldown_reason"] is None
