from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import PasswordService

REGRESSION_FIXTURE_DIR = Path("tests/fixtures/scholar/regression")
SAFETY_STATE_KEYS = {
    "cooldown_active",
    "cooldown_reason",
    "cooldown_reason_label",
    "cooldown_until",
    "cooldown_remaining_seconds",
    "recommended_action",
    "counters",
}
SAFETY_COUNTER_KEYS = {
    "consecutive_blocked_runs",
    "consecutive_network_runs",
    "cooldown_entry_count",
    "blocked_start_count",
    "last_blocked_failure_count",
    "last_network_failure_count",
    "last_evaluated_run_id",
}
ACTIVE_RUN_STATUSES = {"running", "resolving"}


def login_user(client: TestClient, *, email: str, password: str) -> None:
    bootstrap_response = client.get("/api/v1/auth/csrf")
    assert bootstrap_response.status_code == 200
    csrf_token = bootstrap_response.json()["data"]["csrf_token"]
    assert isinstance(csrf_token, str) and csrf_token

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
        },
        headers={"X-CSRF-Token": csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["authenticated"] is True


async def insert_user(
    db_session: AsyncSession,
    *,
    email: str,
    password: str,
    is_admin: bool = False,
    is_active: bool = True,
) -> int:
    password_service = PasswordService()
    result = await db_session.execute(
        text(
            """
            INSERT INTO users (email, password_hash, is_active, is_admin)
            VALUES (:email, :password_hash, :is_active, :is_admin)
            RETURNING id
            """
        ),
        {
            "email": email,
            "password_hash": password_service.hash_password(password),
            "is_active": is_active,
            "is_admin": is_admin,
        },
    )
    user_id = int(result.scalar_one())
    await db_session.commit()
    return user_id


def api_bootstrap_csrf_headers(client: TestClient) -> dict[str, str]:
    bootstrap_response = client.get("/api/v1/auth/csrf")
    assert bootstrap_response.status_code == 200
    payload = bootstrap_response.json()["data"]
    token = payload["csrf_token"]
    assert isinstance(token, str) and token
    return {"X-CSRF-Token": token}


def api_csrf_headers(client: TestClient) -> dict[str, str]:
    me_response = client.get("/api/v1/auth/me")
    assert me_response.status_code == 200
    body = me_response.json()
    token = body["data"]["csrf_token"]
    assert isinstance(token, str) and token
    return {"X-CSRF-Token": token}


def regression_fixture(name: str) -> str:
    return (REGRESSION_FIXTURE_DIR / name).read_text(encoding="utf-8")


def assert_safety_state_contract(payload: dict[str, object]) -> None:
    assert set(payload.keys()) == SAFETY_STATE_KEYS
    counters = payload["counters"]
    assert isinstance(counters, dict)
    assert set(counters.keys()) == SAFETY_COUNTER_KEYS


async def wait_for_run_complete(
    client: TestClient,
    run_id: int,
    *,
    max_retries: int = 300,
    poll_interval: float = 0.2,
) -> dict:
    for _ in range(max_retries):
        await asyncio.sleep(poll_interval)
        r = client.get(f"/api/v1/runs/{run_id}")
        assert r.status_code == 200
        data = r.json()["data"]
        if data["run"]["status"] not in ACTIVE_RUN_STATUSES:
            return data
    r = client.get(f"/api/v1/runs/{run_id}")
    return r.json()["data"]


async def seed_publication_link_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_id: str,
    title: str,
    fingerprint: str,
) -> tuple[int, int]:
    scholar_result = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, true)
            RETURNING id
            """
        ),
        {"user_id": user_id, "scholar_id": scholar_id, "display_name": scholar_id},
    )
    scholar_profile_id = int(scholar_result.scalar_one())
    publication_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 4)
            RETURNING id
            """
        ),
        {"fingerprint": fingerprint, "title_raw": title, "title_normalized": title.lower()},
    )
    publication_id = int(publication_result.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read)
            VALUES (:scholar_profile_id, :publication_id, false)
            """
        ),
        {"scholar_profile_id": scholar_profile_id, "publication_id": publication_id},
    )
    await db_session.commit()
    return scholar_profile_id, publication_id
