import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from tests.integration.helpers import extract_csrf_token, insert_user, login_user


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_users_page_is_admin_only(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="member@example.com",
        password="member-pass",
        is_admin=False,
    )

    client = TestClient(app)
    login_user(client, email="member@example.com", password="member-pass")

    response = client.get("/users")

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required."


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_non_admin_dashboard_hides_users_nav(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="member@example.com",
        password="member-pass",
        is_admin=False,
    )

    client = TestClient(app)
    login_user(client, email="member@example.com", password="member-pass")
    dashboard = client.get("/")

    assert dashboard.status_code == 200
    assert ">Users<" not in dashboard.text


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_admin_dashboard_shows_users_nav(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="admin@example.com",
        password="admin-pass",
        is_admin=True,
    )

    client = TestClient(app)
    login_user(client, email="admin@example.com", password="admin-pass")
    dashboard = client.get("/")

    assert dashboard.status_code == 200
    assert ">Users<" in dashboard.text


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_admin_can_create_and_deactivate_user(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="admin@example.com",
        password="admin-pass",
        is_admin=True,
    )

    client = TestClient(app)
    login_user(client, email="admin@example.com", password="admin-pass")

    users_page = client.get("/users")
    csrf_token = extract_csrf_token(users_page.text)
    create_response = client.post(
        "/users",
        data={
            "email": "new-user@example.com",
            "password": "new-user-pass",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 303
    assert create_response.headers["location"].startswith("/users")

    created_user_id_result = await db_session.execute(
        text("SELECT id FROM users WHERE email = 'new-user@example.com'")
    )
    created_user_id = int(created_user_id_result.scalar_one())

    users_page_after_create = client.get("/users")
    csrf_after_create = extract_csrf_token(users_page_after_create.text)
    toggle_response = client.post(
        f"/users/{created_user_id}/toggle-active",
        data={"csrf_token": csrf_after_create},
        follow_redirects=False,
    )
    assert toggle_response.status_code == 303

    status_result = await db_session.execute(
        text("SELECT is_active FROM users WHERE id = :user_id"),
        {"user_id": created_user_id},
    )
    assert status_result.scalar_one() is False


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_admin_can_reset_user_password(db_session: AsyncSession) -> None:
    target_user_id = await insert_user(
        db_session,
        email="target@example.com",
        password="old-password",
        is_admin=False,
    )
    await insert_user(
        db_session,
        email="admin@example.com",
        password="admin-pass",
        is_admin=True,
    )

    client = TestClient(app)
    login_user(client, email="admin@example.com", password="admin-pass")

    users_page = client.get("/users")
    csrf_token = extract_csrf_token(users_page.text)
    reset_response = client.post(
        f"/users/{target_user_id}/reset-password",
        data={
            "new_password": "new-password",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert reset_response.status_code == 303

    users_page_after_reset = client.get("/users")
    logout_csrf = extract_csrf_token(users_page_after_reset.text)
    client.post(
        "/logout",
        data={"csrf_token": logout_csrf},
        follow_redirects=False,
    )

    failed_login_page = client.get("/login")
    failed_login_csrf = extract_csrf_token(failed_login_page.text)
    failed_login = client.post(
        "/login",
        data={
            "email": "target@example.com",
            "password": "old-password",
            "csrf_token": failed_login_csrf,
        },
        follow_redirects=False,
    )
    assert failed_login.status_code == 401

    login_user(client, email="target@example.com", password="new-password")


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_admin_cannot_deactivate_self(db_session: AsyncSession) -> None:
    admin_user_id = await insert_user(
        db_session,
        email="admin@example.com",
        password="admin-pass",
        is_admin=True,
    )
    client = TestClient(app)
    login_user(client, email="admin@example.com", password="admin-pass")

    users_page = client.get("/users")
    csrf_token = extract_csrf_token(users_page.text)
    response = client.post(
        f"/users/{admin_user_id}/toggle-active",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/users")
    result = await db_session.execute(
        text("SELECT is_active FROM users WHERE id = :user_id"),
        {"user_id": admin_user_id},
    )
    assert result.scalar_one() is True
