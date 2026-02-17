from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.services import scholars as scholar_service
from app.theme import resolve_theme
from app.web import common

logger = logging.getLogger(__name__)

router = APIRouter()


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


async def _render_scholars_page(
    request: Request,
    *,
    db_session: AsyncSession,
    current_user,
    theme_name: str,
    notice: str | None = None,
    page_error: str | None = None,
    status_code: int = status.HTTP_200_OK,
    form_scholar_id: str = "",
    form_display_name: str = "",
) -> HTMLResponse:
    scholars = await scholar_service.list_scholars_for_user(
        db_session,
        user_id=current_user.id,
    )
    scholar_items = []
    for scholar in scholars:
        scholar_items.append(
            {
                "id": scholar.id,
                "scholar_id": scholar.scholar_id,
                "display_name": scholar.display_name or "Unnamed",
                "is_enabled": scholar.is_enabled,
                "baseline_completed": scholar.baseline_completed,
                "last_run_status": (
                    scholar.last_run_status.value
                    if scholar.last_run_status is not None
                    else "never"
                ),
                "last_run_dt": _format_dt(scholar.last_run_dt),
            }
        )
    context = common.build_template_context(
        request,
        page_title="Scholars",
        active_nav="scholars",
        theme_name=theme_name,
        session_user=common.to_session_user(current_user),
        notice=notice,
        page_error=page_error,
    )
    context["scholars"] = scholar_items
    context["form_scholar_id"] = form_scholar_id
    context["form_display_name"] = form_display_name
    return common.templates.TemplateResponse(
        request=request,
        name="scholars.html",
        context=context,
        status_code=status_code,
    )


@router.get("/scholars", response_class=HTMLResponse)
async def scholars_page(
    request: Request,
    theme: str | None = None,
    db_session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()
    return await _render_scholars_page(
        request,
        db_session=db_session,
        current_user=current_user,
        theme_name=resolve_theme(theme),
        notice=request.query_params.get("notice"),
        page_error=request.query_params.get("error"),
    )


@router.post("/scholars")
async def create_scholar(
    request: Request,
    scholar_id: Annotated[str, Form()],
    display_name: Annotated[str, Form()] = "",
    db_session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()
    active_theme = resolve_theme(None)
    try:
        created_profile = await scholar_service.create_scholar_for_user(
            db_session,
            user_id=current_user.id,
            scholar_id=scholar_id,
            display_name=display_name,
        )
    except scholar_service.ScholarServiceError as exc:
        logger.info(
            "scholars.create_failed",
            extra={
                "event": "scholars.create_failed",
                "user_id": current_user.id,
                "scholar_id": scholar_id.strip(),
            },
        )
        return await _render_scholars_page(
            request,
            db_session=db_session,
            current_user=current_user,
            theme_name=active_theme,
            page_error=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
            form_scholar_id=scholar_id,
            form_display_name=display_name,
        )
    label = created_profile.display_name or created_profile.scholar_id
    logger.info(
        "scholars.created",
        extra={
            "event": "scholars.created",
            "user_id": current_user.id,
            "scholar_profile_id": created_profile.id,
        },
    )
    return common.redirect_with_message("/scholars", notice=f"Scholar added: {label}")


@router.post("/scholars/{scholar_profile_id}/toggle")
async def toggle_scholar(
    request: Request,
    scholar_profile_id: int,
    db_session: AsyncSession = Depends(get_db_session),
):
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()

    profile = await scholar_service.get_user_scholar_by_id(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Scholar not found.")
    updated_profile = await scholar_service.toggle_scholar_enabled(
        db_session,
        profile=profile,
    )
    status_label = "enabled" if updated_profile.is_enabled else "disabled"
    logger.info(
        "scholars.toggled",
        extra={
            "event": "scholars.toggled",
            "user_id": current_user.id,
            "scholar_profile_id": updated_profile.id,
            "is_enabled": updated_profile.is_enabled,
        },
    )
    return common.redirect_with_message(
        "/scholars",
        notice=f"Scholar {status_label}: {updated_profile.scholar_id}",
    )


@router.post("/scholars/{scholar_profile_id}/delete")
async def delete_scholar(
    request: Request,
    scholar_profile_id: int,
    db_session: AsyncSession = Depends(get_db_session),
):
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()

    profile = await scholar_service.get_user_scholar_by_id(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Scholar not found.")
    deleted_label = profile.display_name or profile.scholar_id
    await scholar_service.delete_scholar(db_session, profile=profile)
    logger.info(
        "scholars.deleted",
        extra={
            "event": "scholars.deleted",
            "user_id": current_user.id,
            "scholar_profile_id": scholar_profile_id,
        },
    )
    return common.redirect_with_message("/scholars", notice=f"Scholar removed: {deleted_label}")
