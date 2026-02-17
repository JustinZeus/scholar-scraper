from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.services import user_settings as user_settings_service
from app.theme import resolve_theme
from app.web import common

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    theme: str | None = None,
    db_session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()

    user_settings = await user_settings_service.get_or_create_settings(
        db_session,
        user_id=current_user.id,
    )
    context = common.build_template_context(
        request,
        page_title="Settings",
        active_nav="settings",
        theme_name=resolve_theme(theme),
        session_user=common.to_session_user(current_user),
        notice=request.query_params.get("notice"),
        page_error=request.query_params.get("error"),
    )
    context["user_settings"] = user_settings
    return common.templates.TemplateResponse(
        request=request,
        name="settings.html",
        context=context,
    )


@router.post("/settings")
async def update_settings(
    request: Request,
    run_interval_minutes: Annotated[str, Form()],
    request_delay_seconds: Annotated[str, Form()],
    auto_run_enabled: Annotated[str | None, Form()] = None,
    db_session: AsyncSession = Depends(get_db_session),
):
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()
    try:
        parsed_interval = user_settings_service.parse_run_interval_minutes(
            run_interval_minutes
        )
        parsed_delay = user_settings_service.parse_request_delay_seconds(
            request_delay_seconds
        )
    except user_settings_service.UserSettingsServiceError as exc:
        return common.redirect_with_message("/settings", error=str(exc))

    user_settings = await user_settings_service.get_or_create_settings(
        db_session,
        user_id=current_user.id,
    )
    await user_settings_service.update_settings(
        db_session,
        settings=user_settings,
        auto_run_enabled=auto_run_enabled == "on",
        run_interval_minutes=parsed_interval,
        request_delay_seconds=parsed_delay,
    )
    logger.info(
        "settings.updated",
        extra={
            "event": "settings.updated",
            "user_id": current_user.id,
            "auto_run_enabled": auto_run_enabled == "on",
            "run_interval_minutes": parsed_interval,
            "request_delay_seconds": parsed_delay,
        },
    )
    return common.redirect_with_message("/settings", notice="Settings updated.")

