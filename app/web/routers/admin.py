from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_auth_service
from app.auth.service import AuthService
from app.db.session import get_db_session
from app.services import users as user_service
from app.theme import resolve_theme
from app.web import common

logger = logging.getLogger(__name__)

router = APIRouter()


async def _render_users_page(
    request: Request,
    *,
    db_session: AsyncSession,
    current_user,
    theme_name: str,
    notice: str | None = None,
    page_error: str | None = None,
    status_code: int = status.HTTP_200_OK,
    form_email: str = "",
    form_is_admin: bool = False,
) -> HTMLResponse:
    users = await user_service.list_users(db_session)
    context = common.build_template_context(
        request,
        page_title="Users",
        active_nav="users",
        theme_name=theme_name,
        session_user=common.to_session_user(current_user),
        notice=notice,
        page_error=page_error,
    )
    context["users"] = users
    context["current_user_id"] = current_user.id
    context["form_email"] = form_email
    context["form_is_admin"] = form_is_admin
    return common.templates.TemplateResponse(
        request=request,
        name="users.html",
        context=context,
        status_code=status_code,
    )


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    theme: str | None = None,
    db_session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return await _render_users_page(
        request,
        db_session=db_session,
        current_user=current_user,
        theme_name=resolve_theme(theme),
        notice=request.query_params.get("notice"),
        page_error=request.query_params.get("error"),
    )


@router.post("/users")
async def create_user(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    is_admin: Annotated[str | None, Form()] = None,
    db_session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> HTMLResponse:
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    active_theme = resolve_theme(None)
    try:
        validated_email = user_service.validate_email(email)
        validated_password = user_service.validate_password(password)
        created_user = await user_service.create_user(
            db_session,
            email=validated_email,
            password_hash=auth_service.hash_password(validated_password),
            is_admin=is_admin == "on",
        )
    except user_service.UserServiceError as exc:
        logger.info(
            "admin.user_create_failed",
            extra={
                "event": "admin.user_create_failed",
                "admin_user_id": current_user.id,
                "reason": "validation_or_conflict",
            },
        )
        return await _render_users_page(
            request,
            db_session=db_session,
            current_user=current_user,
            theme_name=active_theme,
            page_error=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
            form_email=email,
            form_is_admin=is_admin == "on",
        )

    logger.info(
        "admin.user_created",
        extra={
            "event": "admin.user_created",
            "admin_user_id": current_user.id,
            "target_user_id": created_user.id,
            "target_is_admin": created_user.is_admin,
        },
    )
    return common.redirect_with_message(
        "/users",
        notice=f"User created: {created_user.email}",
    )


@router.post("/users/{user_id}/toggle-active")
async def toggle_user_active(
    request: Request,
    user_id: int,
    db_session: AsyncSession = Depends(get_db_session),
):
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    target_user = await user_service.get_user_by_id(db_session, user_id)
    if target_user is None:
        return common.redirect_with_message("/users", error="User not found.")
    if target_user.id == current_user.id and target_user.is_active:
        return common.redirect_with_message("/users", error="You cannot deactivate your own account.")

    updated_user = await user_service.set_user_active(
        db_session,
        user=target_user,
        is_active=not target_user.is_active,
    )
    status_label = "activated" if updated_user.is_active else "deactivated"
    logger.info(
        "admin.user_active_toggled",
        extra={
            "event": "admin.user_active_toggled",
            "admin_user_id": current_user.id,
            "target_user_id": updated_user.id,
            "is_active": updated_user.is_active,
        },
    )
    return common.redirect_with_message("/users", notice=f"User {status_label}: {updated_user.email}")


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    request: Request,
    user_id: int,
    new_password: Annotated[str, Form()],
    db_session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
):
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    target_user = await user_service.get_user_by_id(db_session, user_id)
    if target_user is None:
        return common.redirect_with_message("/users", error="User not found.")
    try:
        validated_password = user_service.validate_password(new_password)
    except user_service.UserServiceError as exc:
        return common.redirect_with_message("/users", error=str(exc))

    await user_service.set_user_password_hash(
        db_session,
        user=target_user,
        password_hash=auth_service.hash_password(validated_password),
    )
    logger.info(
        "admin.user_password_reset",
        extra={
            "event": "admin.user_password_reset",
            "admin_user_id": current_user.id,
            "target_user_id": target_user.id,
        },
    )
    return common.redirect_with_message("/users", notice=f"Password reset: {target_user.email}")

