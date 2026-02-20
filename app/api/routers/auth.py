from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiException
from app.api.deps import get_api_current_user
from app.api.responses import success_payload
from app.api.schemas import (
    AuthMeEnvelope,
    ChangePasswordRequest,
    CsrfBootstrapEnvelope,
    LoginEnvelope,
    LoginRequest,
    MessageEnvelope,
)
from app.auth.deps import get_auth_service, get_login_rate_limiter
from app.auth.rate_limit import SlidingWindowRateLimiter
from app.auth import runtime as auth_runtime
from app.auth.service import AuthService
from app.auth.session import set_session_user
from app.db.models import User
from app.db.session import get_db_session
from app.security.csrf import ensure_csrf_token
from app.services.domains.users import application as user_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["api-auth"])


def _login_limiter_key_and_email(request: Request, payload: LoginRequest) -> tuple[str, str]:
    return auth_runtime.login_rate_limit_key(request, payload.email), payload.email.strip().lower()


def _raise_rate_limited(normalized_email: str, retry_after_seconds: int) -> None:
    logger.warning(
        "api.auth.login_rate_limited",
        extra={
            "event": "api.auth.login_rate_limited",
            "email": normalized_email,
            "retry_after_seconds": retry_after_seconds,
        },
    )
    raise ApiException(
        status_code=429,
        code="rate_limited",
        message="Too many login attempts. Please try again later.",
        details={"retry_after_seconds": retry_after_seconds},
    )


def _serialize_user_payload(user: User) -> dict[str, object]:
    return {
        "id": int(user.id),
        "email": user.email,
        "is_admin": bool(user.is_admin),
        "is_active": bool(user.is_active),
    }


def _raise_invalid_credentials(*, normalized_email: str) -> None:
    logger.info(
        "api.auth.login_failed",
        extra={"event": "api.auth.login_failed", "email": normalized_email},
    )
    raise ApiException(
        status_code=401,
        code="invalid_credentials",
        message="Invalid email or password.",
    )


@router.post(
    "/login",
    response_model=LoginEnvelope,
)
async def login(
    payload: LoginRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
    rate_limiter: SlidingWindowRateLimiter = Depends(get_login_rate_limiter),
):
    limiter_key, normalized_email = _login_limiter_key_and_email(request, payload)
    decision = rate_limiter.check(limiter_key)
    if not decision.allowed:
        _raise_rate_limited(normalized_email, int(decision.retry_after_seconds))

    user = await auth_service.authenticate_user(
        db_session,
        email=payload.email,
        password=payload.password,
    )
    if user is None:
        rate_limiter.record_failure(limiter_key)
        _raise_invalid_credentials(normalized_email=normalized_email)

    rate_limiter.reset(limiter_key)
    set_session_user(
        request,
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
    )
    logger.info(
        "api.auth.login_succeeded",
        extra={
            "event": "api.auth.login_succeeded",
            "user_id": user.id,
            "is_admin": user.is_admin,
        },
    )
    return success_payload(
        request,
        data={
            "authenticated": True,
            "csrf_token": ensure_csrf_token(request),
            "user": _serialize_user_payload(user),
        },
    )


@router.get(
    "/me",
    response_model=AuthMeEnvelope,
)
async def get_current_session(
    request: Request,
    current_user: User = Depends(get_api_current_user),
):
    return success_payload(
        request,
        data={
            "authenticated": True,
            "csrf_token": ensure_csrf_token(request),
            "user": _serialize_user_payload(current_user),
        },
    )


@router.get(
    "/csrf",
    response_model=CsrfBootstrapEnvelope,
)
async def get_csrf_bootstrap(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    current_user = await auth_runtime.get_authenticated_user(request, db_session)
    return success_payload(
        request,
        data={
            "csrf_token": ensure_csrf_token(request),
            "authenticated": current_user is not None,
        },
    )


@router.post(
    "/change-password",
    response_model=MessageEnvelope,
)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_api_current_user),
    db_session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
):
    if not auth_service.verify_password(
        password_hash=current_user.password_hash,
        password=payload.current_password,
    ):
        raise ApiException(
            status_code=400,
            code="invalid_current_password",
            message="Current password is incorrect.",
        )
    if payload.new_password != payload.confirm_password:
        raise ApiException(
            status_code=400,
            code="password_confirmation_mismatch",
            message="New password and confirmation do not match.",
        )
    try:
        validated_password = user_service.validate_password(payload.new_password)
    except user_service.UserServiceError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_password",
            message=str(exc),
        ) from exc

    await user_service.set_user_password_hash(
        db_session,
        user=current_user,
        password_hash=auth_service.hash_password(validated_password),
    )
    logger.info(
        "api.auth.password_changed",
        extra={
            "event": "api.auth.password_changed",
            "user_id": int(current_user.id),
        },
    )
    return success_payload(
        request,
        data={"message": "Password updated successfully."},
    )


@router.post(
    "/logout",
    response_model=MessageEnvelope,
)
async def logout(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
):
    current_user = await auth_runtime.get_authenticated_user(request, db_session)
    auth_runtime.invalidate_session(request)
    logger.info(
        "api.auth.logout",
        extra={
            "event": "api.auth.logout",
            "user_id": int(current_user.id) if current_user is not None else None,
        },
    )
    return success_payload(
        request,
        data={
            "message": "Logged out.",
        },
    )
