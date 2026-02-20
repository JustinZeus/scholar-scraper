from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserServiceError(ValueError):
    """Raised for expected user-management validation failures."""


def normalize_email(value: str) -> str:
    return value.strip().lower()


def validate_email(value: str) -> str:
    email = normalize_email(value)
    if not EMAIL_PATTERN.fullmatch(email):
        raise UserServiceError("Enter a valid email address.")
    return email


def validate_password(value: str) -> str:
    password = value.strip()
    if len(password) < 8:
        raise UserServiceError("Password must be at least 8 characters.")
    return password


async def get_user_by_id(db_session: AsyncSession, user_id: int) -> User | None:
    result = await db_session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_email(db_session: AsyncSession, email: str) -> User | None:
    result = await db_session.execute(
        select(User).where(User.email == normalize_email(email))
    )
    return result.scalar_one_or_none()


async def list_users(db_session: AsyncSession) -> list[User]:
    result = await db_session.execute(select(User).order_by(User.email.asc()))
    return list(result.scalars().all())


async def create_user(
    db_session: AsyncSession,
    *,
    email: str,
    password_hash: str,
    is_admin: bool,
) -> User:
    user = User(
        email=validate_email(email),
        password_hash=password_hash,
        is_admin=is_admin,
        is_active=True,
    )
    db_session.add(user)
    try:
        await db_session.commit()
    except IntegrityError as exc:
        await db_session.rollback()
        raise UserServiceError("A user with that email already exists.") from exc
    await db_session.refresh(user)
    return user


async def set_user_active(
    db_session: AsyncSession,
    *,
    user: User,
    is_active: bool,
) -> User:
    user.is_active = is_active
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def set_user_password_hash(
    db_session: AsyncSession,
    *,
    user: User,
    password_hash: str,
) -> User:
    user.password_hash = password_hash
    await db_session.commit()
    await db_session.refresh(user)
    return user

