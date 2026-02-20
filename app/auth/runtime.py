from __future__ import annotations

import logging

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import clear_session_user, get_session_user, set_session_user
from app.db.models import User
from app.security.csrf import CSRF_SESSION_KEY
from app.services.domains.users import application as user_service

logger = logging.getLogger(__name__)


def invalidate_session(request: Request) -> None:
    clear_session_user(request)
    request.session.pop(CSRF_SESSION_KEY, None)


async def get_authenticated_user(
    request: Request,
    db_session: AsyncSession,
) -> User | None:
    session_user = get_session_user(request)
    if session_user is None:
        return None

    user = await user_service.get_user_by_id(db_session, session_user.id)
    if user is None or not user.is_active:
        logger.info(
            "auth.session_invalidated",
            extra={
                "event": "auth.session_invalidated",
                "session_user_id": session_user.id,
            },
        )
        invalidate_session(request)
        return None

    if user.email != session_user.email or user.is_admin != session_user.is_admin:
        set_session_user(
            request,
            user_id=user.id,
            email=user.email,
            is_admin=user.is_admin,
        )

    return user


def login_rate_limit_key(request: Request, email: str) -> str:
    client_host = request.client.host if request.client is not None else "unknown"
    normalized_email = email.strip().lower()
    return f"{client_host}:{normalized_email or '<empty>'}"
