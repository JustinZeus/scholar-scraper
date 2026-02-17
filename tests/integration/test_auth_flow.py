import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.testclient import TestClient

from app.auth.security import PasswordService
from app.main import app

CSRF_TOKEN_PATTERN = re.compile(r'name="csrf_token" value="([^"]+)"')


def _extract_csrf_token(html: str) -> str:
    match = CSRF_TOKEN_PATTERN.search(html)
    assert match is not None
    return match.group(1)


@pytest.mark.integration
def test_dashboard_requires_authentication() -> None:
    client = TestClient(app)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_login_with_valid_credentials_allows_access(db_session: AsyncSession) -> None:
    password_service = PasswordService()
    await db_session.execute(
        text(
            """
            INSERT INTO users (email, password_hash, is_active, is_admin)
            VALUES (:email, :password_hash, :is_active, :is_admin)
            """
        ),
        {
            "email": "reader@example.com",
            "password_hash": password_service.hash_password("correct-password"),
            "is_active": True,
            "is_admin": False,
        },
    )
    await db_session.commit()

    client = TestClient(app)
    login_page = client.get("/login")
    csrf_token = _extract_csrf_token(login_page.text)
    login_response = client.post(
        "/login",
        data={
            "email": "reader@example.com",
            "password": "correct-password",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )

    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/"

    dashboard_response = client.get("/")
    assert dashboard_response.status_code == 200
    assert "reader@example.com" in dashboard_response.text
    assert 'data-test="home-hero"' in dashboard_response.text


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_login_rejects_inactive_user(db_session: AsyncSession) -> None:
    password_service = PasswordService()
    await db_session.execute(
        text(
            """
            INSERT INTO users (email, password_hash, is_active, is_admin)
            VALUES (:email, :password_hash, :is_active, :is_admin)
            """
        ),
        {
            "email": "inactive@example.com",
            "password_hash": password_service.hash_password("correct-password"),
            "is_active": False,
            "is_admin": False,
        },
    )
    await db_session.commit()

    client = TestClient(app)
    login_page = client.get("/login")
    csrf_token = _extract_csrf_token(login_page.text)
    login_response = client.post(
        "/login",
        data={
            "email": "inactive@example.com",
            "password": "correct-password",
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )

    assert login_response.status_code == 401
    assert "Invalid email or password." in login_response.text

