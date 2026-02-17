from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import PasswordService

CSRF_TOKEN_PATTERN = re.compile(r'name="csrf_token" value="([^"]+)"')


def extract_csrf_token(html: str) -> str:
    match = CSRF_TOKEN_PATTERN.search(html)
    assert match is not None
    return match.group(1)


def login_user(client: TestClient, *, email: str, password: str) -> None:
    login_page = client.get("/login")
    csrf_token = extract_csrf_token(login_page.text)
    response = client.post(
        "/login",
        data={
            "email": email,
            "password": password,
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


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

