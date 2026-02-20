from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_admin_user
from app.api.errors import ApiException
from app.api.responses import success_payload
from app.api.schemas import (
    AdminResetPasswordRequest,
    AdminUserActiveUpdateRequest,
    AdminUserCreateRequest,
    AdminUserEnvelope,
    AdminUsersListEnvelope,
    MessageEnvelope,
)
from app.auth.deps import get_auth_service
from app.auth.service import AuthService
from app.db.models import User
from app.db.session import get_db_session
from app.services.domains.users import application as user_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/users", tags=["api-admin-users"])


def _serialize_user(user: User) -> dict[str, object]:
    return {
        "id": int(user.id),
        "email": user.email,
        "is_active": bool(user.is_active),
        "is_admin": bool(user.is_admin),
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


@router.get(
    "",
    response_model=AdminUsersListEnvelope,
)
async def list_users(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(get_api_admin_user),
):
    users = await user_service.list_users(db_session)
    logger.info(
        "api.admin.users_listed",
        extra={
            "event": "api.admin.users_listed",
            "admin_user_id": int(admin_user.id),
            "user_count": len(users),
        },
    )
    return success_payload(
        request,
        data={
            "users": [_serialize_user(user) for user in users],
        },
    )


@router.post(
    "",
    response_model=AdminUserEnvelope,
    status_code=201,
)
async def create_user(
    payload: AdminUserCreateRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
    admin_user: User = Depends(get_api_admin_user),
):
    try:
        validated_email = user_service.validate_email(payload.email)
        validated_password = user_service.validate_password(payload.password)
        created_user = await user_service.create_user(
            db_session,
            email=validated_email,
            password_hash=auth_service.hash_password(validated_password),
            is_admin=bool(payload.is_admin),
        )
    except user_service.UserServiceError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_user_input",
            message=str(exc),
        ) from exc

    logger.info(
        "api.admin.user_created",
        extra={
            "event": "api.admin.user_created",
            "admin_user_id": int(admin_user.id),
            "target_user_id": int(created_user.id),
            "target_is_admin": bool(created_user.is_admin),
        },
    )
    return success_payload(
        request,
        data=_serialize_user(created_user),
    )


@router.patch(
    "/{user_id}/active",
    response_model=AdminUserEnvelope,
)
async def set_user_active(
    user_id: int,
    payload: AdminUserActiveUpdateRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(get_api_admin_user),
):
    target_user = await user_service.get_user_by_id(db_session, user_id)
    if target_user is None:
        raise ApiException(
            status_code=404,
            code="user_not_found",
            message="User not found.",
        )
    if (
        int(target_user.id) == int(admin_user.id)
        and bool(target_user.is_active)
        and not bool(payload.is_active)
    ):
        raise ApiException(
            status_code=400,
            code="cannot_deactivate_self",
            message="You cannot deactivate your own account.",
        )
    updated_user = await user_service.set_user_active(
        db_session,
        user=target_user,
        is_active=bool(payload.is_active),
    )
    logger.info(
        "api.admin.user_active_updated",
        extra={
            "event": "api.admin.user_active_updated",
            "admin_user_id": int(admin_user.id),
            "target_user_id": int(updated_user.id),
            "is_active": bool(updated_user.is_active),
        },
    )
    return success_payload(
        request,
        data=_serialize_user(updated_user),
    )


@router.post(
    "/{user_id}/reset-password",
    response_model=MessageEnvelope,
)
async def reset_user_password(
    user_id: int,
    payload: AdminResetPasswordRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    auth_service: AuthService = Depends(get_auth_service),
    admin_user: User = Depends(get_api_admin_user),
):
    target_user = await user_service.get_user_by_id(db_session, user_id)
    if target_user is None:
        raise ApiException(
            status_code=404,
            code="user_not_found",
            message="User not found.",
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
        user=target_user,
        password_hash=auth_service.hash_password(validated_password),
    )
    logger.info(
        "api.admin.user_password_reset",
        extra={
            "event": "api.admin.user_password_reset",
            "admin_user_id": int(admin_user.id),
            "target_user_id": int(target_user.id),
        },
    )
    return success_payload(
        request,
        data={"message": f"Password reset: {target_user.email}"},
    )
