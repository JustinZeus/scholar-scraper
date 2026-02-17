from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiException
from app.auth import runtime as auth_runtime
from app.db.models import User
from app.db.session import get_db_session


async def get_api_current_user(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
) -> User:
    current_user = await auth_runtime.get_authenticated_user(request, db_session)
    if current_user is None:
        raise ApiException(
            status_code=401,
            code="auth_required",
            message="Authentication required.",
        )
    return current_user


async def get_api_admin_user(
    current_user: User = Depends(get_api_current_user),
) -> User:
    if not current_user.is_admin:
        raise ApiException(
            status_code=403,
            code="forbidden",
            message="Admin access required.",
        )
    return current_user
