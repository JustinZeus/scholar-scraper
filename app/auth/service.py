from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import PasswordService
from app.db.models import User


class AuthService:
    def __init__(self, password_service: PasswordService) -> None:
        self._password_service = password_service

    async def authenticate_user(
        self,
        db_session: AsyncSession,
        *,
        email: str,
        password: str,
    ) -> User | None:
        normalized_email = email.strip().lower()
        if not normalized_email or not password:
            return None
        result = await db_session.execute(
            select(User).where(User.email == normalized_email)
        )
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            return None
        if not self._password_service.verify_password(user.password_hash, password):
            return None
        return user

    def hash_password(self, password: str) -> str:
        return self._password_service.hash_password(password)

    def verify_password(self, *, password_hash: str, password: str) -> bool:
        return self._password_service.verify_password(password_hash, password)
