from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from tests.integration.helpers import (
    api_bootstrap_csrf_headers,
    insert_user,
    login_user,
)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_me_requires_authentication() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    payload = response.json()
    assert payload["error"]["code"] == "auth_required"
    assert payload["error"]["message"] == "Authentication required."
    assert "request_id" in payload["meta"]


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_envelope_contract_for_success_and_csrf_error() -> None:
    client = TestClient(app)

    success_response = client.get("/api/v1/auth/csrf")
    assert success_response.status_code == 200
    success_payload = success_response.json()
    assert set(success_payload.keys()) == {"data", "meta"}
    assert isinstance(success_payload["data"]["csrf_token"], str)
    assert set(success_payload["meta"].keys()) == {"request_id"}

    error_response = client.post(
        "/api/v1/auth/login",
        json={"email": "missing-csrf@example.com", "password": "irrelevant"},
    )
    assert error_response.status_code == 403
    error_payload = error_response.json()
    assert set(error_payload.keys()) == {"error", "meta"}
    assert set(error_payload["error"].keys()) == {"code", "message", "details"}
    assert error_payload["error"]["code"] == "csrf_invalid"
    assert error_payload["error"]["details"] is None
    assert set(error_payload["meta"].keys()) == {"request_id"}


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_csrf_bootstrap_returns_token_for_anonymous_and_authenticated(
    db_session: AsyncSession,
) -> None:
    await insert_user(
        db_session,
        email="api-bootstrap@example.com",
        password="api-password",
    )
    client = TestClient(app)

    anonymous_response = client.get("/api/v1/auth/csrf")
    assert anonymous_response.status_code == 200
    anonymous_payload = anonymous_response.json()["data"]
    assert isinstance(anonymous_payload["csrf_token"], str)
    assert anonymous_payload["authenticated"] is False

    login_user(client, email="api-bootstrap@example.com", password="api-password")
    authenticated_response = client.get("/api/v1/auth/csrf")
    assert authenticated_response.status_code == 200
    authenticated_payload = authenticated_response.json()["data"]
    assert isinstance(authenticated_payload["csrf_token"], str)
    assert authenticated_payload["authenticated"] is True


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_me_returns_user_and_csrf_token(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="api-me@example.com",
        password="api-password",
    )

    client = TestClient(app)
    login_user(client, email="api-me@example.com", password="api-password")

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["authenticated"] is True
    assert payload["data"]["user"]["email"] == "api-me@example.com"
    assert isinstance(payload["data"]["csrf_token"], str)
    assert payload["meta"]["request_id"]


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_login_and_change_password_flow(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="api-login@example.com",
        password="old-password",
    )
    client = TestClient(app)

    missing_csrf = client.post(
        "/api/v1/auth/login",
        json={"email": "api-login@example.com", "password": "old-password"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_missing"

    login_headers = api_bootstrap_csrf_headers(client)
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "api-login@example.com", "password": "old-password"},
        headers=login_headers,
    )
    assert login_response.status_code == 200
    login_payload = login_response.json()["data"]
    assert login_payload["authenticated"] is True
    assert login_payload["user"]["email"] == "api-login@example.com"
    assert isinstance(login_payload["csrf_token"], str)

    bad_change_response = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "not-correct",
            "new_password": "new-password",
            "confirm_password": "new-password",
        },
        headers={"X-CSRF-Token": login_payload["csrf_token"]},
    )
    assert bad_change_response.status_code == 400
    assert bad_change_response.json()["error"]["code"] == "invalid_current_password"

    change_response = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "old-password",
            "new_password": "new-password",
            "confirm_password": "new-password",
        },
        headers={"X-CSRF-Token": login_payload["csrf_token"]},
    )
    assert change_response.status_code == 200
    assert change_response.json()["data"]["message"] == "Password updated successfully."

    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": login_payload["csrf_token"]},
    )
    assert logout_response.status_code == 200

    relogin_headers = api_bootstrap_csrf_headers(client)
    old_password_login = client.post(
        "/api/v1/auth/login",
        json={"email": "api-login@example.com", "password": "old-password"},
        headers=relogin_headers,
    )
    assert old_password_login.status_code == 401
    assert old_password_login.json()["error"]["code"] == "invalid_credentials"

    fresh_headers = api_bootstrap_csrf_headers(client)
    new_password_login = client.post(
        "/api/v1/auth/login",
        json={"email": "api-login@example.com", "password": "new-password"},
        headers=fresh_headers,
    )
    assert new_password_login.status_code == 200
    assert new_password_login.json()["data"]["authenticated"] is True
