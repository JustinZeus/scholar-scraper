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
from app.services import run_safety as run_safety_service
from app.services import user_settings as user_settings_service
from app.settings import settings as settings_module

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["api-settings"])


def _serialize_settings(user_settings) -> dict[str, object]:
    min_run_interval_minutes = user_settings_service.resolve_run_interval_minimum(
        settings_module.ingestion_min_run_interval_minutes
    )
    min_request_delay_seconds = user_settings_service.resolve_request_delay_minimum(
        settings_module.ingestion_min_request_delay_seconds
    )
    return {
        "auto_run_enabled": bool(user_settings.auto_run_enabled) and settings_module.ingestion_automation_allowed,
        "run_interval_minutes": int(user_settings.run_interval_minutes),
        "request_delay_seconds": int(user_settings.request_delay_seconds),
        "nav_visible_pages": list(user_settings.nav_visible_pages or []),
        "policy": {
            "min_run_interval_minutes": min_run_interval_minutes,
            "min_request_delay_seconds": min_request_delay_seconds,
            "automation_allowed": bool(settings_module.ingestion_automation_allowed),
            "manual_run_allowed": bool(settings_module.ingestion_manual_run_allowed),
            "blocked_failure_threshold": max(1, int(settings_module.ingestion_alert_blocked_failure_threshold)),
            "network_failure_threshold": max(1, int(settings_module.ingestion_alert_network_failure_threshold)),
            "cooldown_blocked_seconds": max(60, int(settings_module.ingestion_safety_cooldown_blocked_seconds)),
            "cooldown_network_seconds": max(60, int(settings_module.ingestion_safety_cooldown_network_seconds)),
        },
        "safety_state": run_safety_service.get_safety_state_payload(user_settings),
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
    user_settings = await user_settings_service.get_or_create_settings(
        db_session,
        user_id=current_user.id,
    )
    previous_safety_state = run_safety_service.get_safety_event_context(user_settings)
    if run_safety_service.clear_expired_cooldown(user_settings):
        await db_session.commit()
        await db_session.refresh(user_settings)
        logger.info(
            "api.settings.safety_cooldown_cleared",
            extra={
                "event": "api.settings.safety_cooldown_cleared",
                "user_id": current_user.id,
                "reason": previous_safety_state.get("cooldown_reason"),
                "cooldown_until": previous_safety_state.get("cooldown_until"),
                "metric_name": "api_settings_safety_cooldown_cleared_total",
                "metric_value": 1,
            },
        )
    return success_payload(
        request,
        data=_serialize_settings(user_settings),
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
    user_settings = await user_settings_service.get_or_create_settings(
        db_session,
        user_id=current_user.id,
    )

    min_run_interval_minutes = user_settings_service.resolve_run_interval_minimum(
        settings_module.ingestion_min_run_interval_minutes
    )
    min_request_delay_seconds = user_settings_service.resolve_request_delay_minimum(
        settings_module.ingestion_min_request_delay_seconds
    )

    try:
        parsed_interval = user_settings_service.parse_run_interval_minutes(
            str(payload.run_interval_minutes),
            minimum=min_run_interval_minutes,
        )
        parsed_delay = user_settings_service.parse_request_delay_seconds(
            str(payload.request_delay_seconds),
            minimum=min_request_delay_seconds,
        )
        parsed_nav_visible_pages = user_settings_service.parse_nav_visible_pages(
            payload.nav_visible_pages
            if payload.nav_visible_pages is not None
            else list(user_settings.nav_visible_pages or user_settings_service.DEFAULT_NAV_VISIBLE_PAGES)
        )
    except user_settings_service.UserSettingsServiceError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_settings",
            message=str(exc),
        ) from exc

    effective_auto_run_enabled = (
        bool(payload.auto_run_enabled) and settings_module.ingestion_automation_allowed
    )

    updated = await user_settings_service.update_settings(
        db_session,
        settings=user_settings,
        auto_run_enabled=effective_auto_run_enabled,
        run_interval_minutes=parsed_interval,
        request_delay_seconds=parsed_delay,
        nav_visible_pages=parsed_nav_visible_pages,
    )
    previous_safety_state = run_safety_service.get_safety_event_context(updated)
    if run_safety_service.clear_expired_cooldown(updated):
        await db_session.commit()
        await db_session.refresh(updated)
        logger.info(
            "api.settings.safety_cooldown_cleared",
            extra={
                "event": "api.settings.safety_cooldown_cleared",
                "user_id": current_user.id,
                "reason": previous_safety_state.get("cooldown_reason"),
                "cooldown_until": previous_safety_state.get("cooldown_until"),
                "metric_name": "api_settings_safety_cooldown_cleared_total",
                "metric_value": 1,
            },
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
