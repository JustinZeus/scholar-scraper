from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import PasswordService

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
