from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_current_user
from app.api.errors import ApiException
from app.api.responses import success_payload
from app.api.schemas import SettingsEnvelope, SettingsUpdateRequest
from app.db.models import User
from app.db.session import get_db_session
from app.services import user_settings as user_settings_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["api-settings"])


def _serialize_settings(settings) -> dict[str, object]:
    return {
        "auto_run_enabled": bool(settings.auto_run_enabled),
        "run_interval_minutes": int(settings.run_interval_minutes),
        "request_delay_seconds": int(settings.request_delay_seconds),
        "nav_visible_pages": list(settings.nav_visible_pages or []),
    }


@router.get(
    "",
    response_model=SettingsEnvelope,
)
async def get_settings(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    settings = await user_settings_service.get_or_create_settings(
        db_session,
        user_id=current_user.id,
    )
    return success_payload(
        request,
        data=_serialize_settings(settings),
    )


@router.put(
    "",
    response_model=SettingsEnvelope,
)
async def update_settings(
    payload: SettingsUpdateRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    settings = await user_settings_service.get_or_create_settings(
        db_session,
        user_id=current_user.id,
    )

    try:
        parsed_interval = user_settings_service.parse_run_interval_minutes(
            str(payload.run_interval_minutes)
        )
        parsed_delay = user_settings_service.parse_request_delay_seconds(
            str(payload.request_delay_seconds)
        )
        parsed_nav_visible_pages = user_settings_service.parse_nav_visible_pages(
            payload.nav_visible_pages
            if payload.nav_visible_pages is not None
            else list(settings.nav_visible_pages or user_settings_service.DEFAULT_NAV_VISIBLE_PAGES)
        )
    except user_settings_service.UserSettingsServiceError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_settings",
            message=str(exc),
        ) from exc

    updated = await user_settings_service.update_settings(
        db_session,
        settings=settings,
        auto_run_enabled=bool(payload.auto_run_enabled),
        run_interval_minutes=parsed_interval,
        request_delay_seconds=parsed_delay,
        nav_visible_pages=parsed_nav_visible_pages,
    )
    logger.info(
        "api.settings.updated",
        extra={
            "event": "api.settings.updated",
            "user_id": current_user.id,
            "auto_run_enabled": updated.auto_run_enabled,
            "run_interval_minutes": updated.run_interval_minutes,
            "request_delay_seconds": updated.request_delay_seconds,
            "nav_visible_pages": updated.nav_visible_pages,
        },
    )
    return success_payload(
        request,
        data=_serialize_settings(updated),
    )
