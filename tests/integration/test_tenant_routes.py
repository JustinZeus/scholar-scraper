import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from tests.integration.helpers import extract_csrf_token, insert_user, login_user


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_user_can_change_own_password(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="reader@example.com",
        password="old-password",
    )

    client = TestClient(app)
    login_user(client, email="reader@example.com", password="old-password")

    account_page = client.get("/account/password")
    csrf_token = extract_csrf_token(account_page.text)
    wrong_current = client.post(
        "/account/password",
        data={
            "current_password": "wrong-password",
            "new_password": "new-password",
            "confirm_password": "new-password",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert wrong_current.status_code == 303
    assert wrong_current.headers["location"].startswith("/account/password")

    account_page_retry = client.get("/account/password")
    retry_csrf = extract_csrf_token(account_page_retry.text)
    success = client.post(
        "/account/password",
        data={
            "current_password": "old-password",
            "new_password": "new-password",
            "confirm_password": "new-password",
            "csrf_token": retry_csrf,
        },
        follow_redirects=False,
    )
    assert success.status_code == 303

    account_page_after = client.get("/account/password")
    logout_csrf = extract_csrf_token(account_page_after.text)
    client.post("/logout", data={"csrf_token": logout_csrf}, follow_redirects=False)

    failed_login_page = client.get("/login")
    failed_login_csrf = extract_csrf_token(failed_login_page.text)
    failed_login = client.post(
        "/login",
        data={
            "email": "reader@example.com",
            "password": "old-password",
            "csrf_token": failed_login_csrf,
        },
        follow_redirects=False,
    )
    assert failed_login.status_code == 401

    login_user(client, email="reader@example.com", password="new-password")


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_scholar_routes_are_tenant_scoped(db_session: AsyncSession) -> None:
    user_a_id = await insert_user(
        db_session,
        email="owner-a@example.com",
        password="owner-a-password",
    )
    user_b_id = await insert_user(
        db_session,
        email="owner-b@example.com",
        password="owner-b-password",
    )

    client = TestClient(app)
    login_user(client, email="owner-a@example.com", password="owner-a-password")

    scholars_page = client.get("/scholars")
    csrf_token = extract_csrf_token(scholars_page.text)
    create_response = client.post(
        "/scholars",
        data={
            "scholar_id": "abcDEF123456",
            "display_name": "Owner A Scholar",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    owner_a_row = await db_session.execute(
        text(
            """
            SELECT user_id
            FROM scholar_profiles
            WHERE scholar_id = 'abcDEF123456'
            """
        )
    )
    assert owner_a_row.scalar_one() == user_a_id

    owner_b_profile = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, :is_enabled)
            RETURNING id
            """
        ),
        {
            "user_id": user_b_id,
            "scholar_id": "zxcvbn654321",
            "display_name": "Owner B Scholar",
            "is_enabled": True,
        },
    )
    owner_b_profile_id = int(owner_b_profile.scalar_one())
    await db_session.commit()

    scholars_page_after_insert = client.get("/scholars")
    csrf_after_insert = extract_csrf_token(scholars_page_after_insert.text)
    forbidden_toggle = client.post(
        f"/scholars/{owner_b_profile_id}/toggle",
        data={"csrf_token": csrf_after_insert},
        follow_redirects=False,
    )
    assert forbidden_toggle.status_code == 404

    owner_b_status = await db_session.execute(
        text("SELECT is_enabled FROM scholar_profiles WHERE id = :profile_id"),
        {"profile_id": owner_b_profile_id},
    )
    assert owner_b_status.scalar_one() is True


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_settings_updates_are_user_scoped(db_session: AsyncSession) -> None:
    user_a_id = await insert_user(
        db_session,
        email="settings-a@example.com",
        password="settings-a-password",
    )
    user_b_id = await insert_user(
        db_session,
        email="settings-b@example.com",
        password="settings-b-password",
    )

    client = TestClient(app)
    login_user(client, email="settings-a@example.com", password="settings-a-password")

    settings_page = client.get("/settings")
    csrf_token = extract_csrf_token(settings_page.text)
    response = client.post(
        "/settings",
        data={
            "auto_run_enabled": "on",
            "run_interval_minutes": "45",
            "request_delay_seconds": "7",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    user_a_settings = await db_session.execute(
        text(
            """
            SELECT auto_run_enabled, run_interval_minutes, request_delay_seconds
            FROM user_settings
            WHERE user_id = :user_id
            """
        ),
        {"user_id": user_a_id},
    )
    assert user_a_settings.one() == (True, 45, 7)

    user_b_settings = await db_session.execute(
        text("SELECT COUNT(*) FROM user_settings WHERE user_id = :user_id"),
        {"user_id": user_b_id},
    )
    assert user_b_settings.scalar_one() == 0

