from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import (
    SessionUser,
    clear_session_user,
    get_session_user,
    set_session_user,
)
from app.db.models import User
from app.security.csrf import CSRF_SESSION_KEY, ensure_csrf_token
from app.services import users as user_service
from app.theme import THEMES

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="app/templates")


def to_session_user(user: User | None) -> SessionUser | None:
    if user is None:
        return None
    return SessionUser(id=user.id, email=user.email, is_admin=user.is_admin)


def build_template_context(
    request: Request,
    *,
    page_title: str,
    active_nav: str,
    theme_name: str,
    session_user: SessionUser | None,
    notice: str | None = None,
    page_error: str | None = None,
) -> dict[str, object]:
    return {
        "active_nav": active_nav,
        "page_title": page_title,
        "theme_name": theme_name,
        "themes": THEMES,
        "session_user": session_user,
        "csrf_token": ensure_csrf_token(request),
        "notice": notice,
        "page_error": page_error,
    }


def redirect_with_message(
    path: str,
    *,
    notice: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    params: dict[str, str] = {}
    if notice:
        params["notice"] = notice
    if error:
        params["error"] = error
    if params:
        path = f"{path}?{urlencode(params)}"
    return RedirectResponse(path, status_code=status.HTTP_303_SEE_OTHER)


def redirect_to_login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


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


def render_login_page(
    request: Request,
    *,
    theme_name: str,
    error_message: str | None = None,
    status_code: int = status.HTTP_200_OK,
    retry_after_seconds: int | None = None,
) -> HTMLResponse:
    context = build_template_context(
        request,
        page_title="Login",
        active_nav="login",
        theme_name=theme_name,
        session_user=None,
    )
    context["error_message"] = error_message
    context["retry_after_seconds"] = retry_after_seconds
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context=context,
        status_code=status_code,
    )

