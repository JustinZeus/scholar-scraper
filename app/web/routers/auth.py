from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_auth_service, get_login_rate_limiter
from app.auth.rate_limit import SlidingWindowRateLimiter
from app.auth.service import AuthService
from app.auth.session import get_session_user, set_session_user
from app.db.session import get_db_session
from app.security.csrf import ensure_csrf_token
from app.services import users as user_service
from app.theme import resolve_theme
from app.web import common

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, theme: str | None = None) -> HTMLResponse:
    active_theme = resolve_theme(theme)
    ensure_csrf_token(request)
    if get_session_user(request) is not None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return common.render_login_page(request, theme_name=active_theme)


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db_session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
    rate_limiter: SlidingWindowRateLimiter = Depends(get_login_rate_limiter),
) -> HTMLResponse:
    active_theme = resolve_theme(None)
    limiter_key = common.login_rate_limit_key(request, email)
    decision = rate_limiter.check(limiter_key)
    normalized_email = email.strip().lower()
    if not decision.allowed:
        logger.warning(
            "auth.login_rate_limited",
            extra={
                "event": "auth.login_rate_limited",
                "email": normalized_email,
                "retry_after_seconds": decision.retry_after_seconds,
            },
        )
        response = common.render_login_page(
            request,
            theme_name=active_theme,
            error_message="Too many login attempts. Please try again later.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            retry_after_seconds=decision.retry_after_seconds,
        )
        response.headers["Retry-After"] = str(decision.retry_after_seconds)
        return response

    user = await auth_service.authenticate_user(
        db_session,
        email=email,
        password=password,
    )
    if user is None:
        rate_limiter.record_failure(limiter_key)
        logger.info(
            "auth.login_failed",
            extra={
                "event": "auth.login_failed",
                "email": normalized_email,
            },
        )
        return common.render_login_page(
            request,
            theme_name=active_theme,
            error_message="Invalid email or password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    rate_limiter.reset(limiter_key)
    set_session_user(
        request,
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
    )
    ensure_csrf_token(request)
    logger.info(
        "auth.login_succeeded",
        extra={
            "event": "auth.login_succeeded",
            "user_id": user.id,
            "is_admin": user.is_admin,
        },
    )
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    session_user = get_session_user(request)
    common.invalidate_session(request)
    logger.info(
        "auth.logout",
        extra={
            "event": "auth.logout",
            "user_id": session_user.id if session_user else None,
        },
    )
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/account/password", response_class=HTMLResponse)
async def account_password_page(
    request: Request,
    theme: str | None = None,
    db_session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()
    return common.templates.TemplateResponse(
        request=request,
        name="account_password.html",
        context=common.build_template_context(
            request,
            page_title="Change Password",
            active_nav="account_password",
            theme_name=resolve_theme(theme),
            session_user=common.to_session_user(current_user),
            notice=request.query_params.get("notice"),
            page_error=request.query_params.get("error"),
        ),
    )


@router.post("/account/password")
async def update_account_password(
    request: Request,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    db_session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> RedirectResponse:
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()
    if not auth_service.verify_password(
        password_hash=current_user.password_hash,
        password=current_password,
    ):
        logger.info(
            "account.password_change_failed",
            extra={
                "event": "account.password_change_failed",
                "user_id": current_user.id,
                "reason": "invalid_current_password",
            },
        )
        return common.redirect_with_message(
            "/account/password",
            error="Current password is incorrect.",
        )
    if new_password != confirm_password:
        logger.info(
            "account.password_change_failed",
            extra={
                "event": "account.password_change_failed",
                "user_id": current_user.id,
                "reason": "confirmation_mismatch",
            },
        )
        return common.redirect_with_message(
            "/account/password",
            error="New password and confirmation do not match.",
        )
    try:
        validated_password = user_service.validate_password(new_password)
    except user_service.UserServiceError as exc:
        logger.info(
            "account.password_change_failed",
            extra={
                "event": "account.password_change_failed",
                "user_id": current_user.id,
                "reason": "validation_error",
            },
        )
        return common.redirect_with_message("/account/password", error=str(exc))

    await user_service.set_user_password_hash(
        db_session,
        user=current_user,
        password_hash=auth_service.hash_password(validated_password),
    )
    logger.info(
        "account.password_changed",
        extra={
            "event": "account.password_changed",
            "user_id": current_user.id,
        },
    )
    return common.redirect_with_message(
        "/account/password",
        notice="Password updated successfully.",
    )

