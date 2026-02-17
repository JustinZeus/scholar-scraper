from __future__ import annotations

import logging
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.services import publications as publication_service
from app.services import scholars as scholar_service
from app.theme import resolve_theme
from app.web import common

logger = logging.getLogger(__name__)

router = APIRouter()

MODE_NEW = "new"
MODE_ALL = "all"


def _resolve_mode(raw_mode: str | None) -> str:
    return publication_service.resolve_mode(raw_mode)


def _parse_scholar_profile_id(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _build_publications_url(*, mode: str, scholar_profile_id: int | None) -> str:
    params: dict[str, str] = {"mode": mode}
    if scholar_profile_id is not None:
        params["scholar_profile_id"] = str(scholar_profile_id)
    return f"/publications?{urlencode(params)}"


def _is_safe_return_to(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return False
    if not value.startswith("/"):
        return False
    return value == "/" or value.startswith("/publications")


@router.get("/publications", response_class=HTMLResponse)
async def publications_page(
    request: Request,
    mode: str | None = None,
    scholar_profile_id: str | None = None,
    theme: str | None = None,
    db_session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()

    resolved_mode = _resolve_mode(mode)
    scholar_id_filter = _parse_scholar_profile_id(scholar_profile_id)
    scholars = await scholar_service.list_scholars_for_user(
        db_session,
        user_id=current_user.id,
    )
    scholar_lookup = {scholar.id: scholar for scholar in scholars}
    if scholar_id_filter not in scholar_lookup:
        scholar_id_filter = None

    publications = await publication_service.list_for_user(
        db_session,
        user_id=current_user.id,
        mode=resolved_mode,
        scholar_profile_id=scholar_id_filter,
        limit=500,
    )
    new_count = await publication_service.count_for_user(
        db_session,
        user_id=current_user.id,
        mode=MODE_NEW,
        scholar_profile_id=scholar_id_filter,
    )
    total_count = await publication_service.count_for_user(
        db_session,
        user_id=current_user.id,
        mode=MODE_ALL,
        scholar_profile_id=scholar_id_filter,
    )
    mode_new_url = _build_publications_url(
        mode=MODE_NEW,
        scholar_profile_id=scholar_id_filter,
    )
    mode_all_url = _build_publications_url(
        mode=MODE_ALL,
        scholar_profile_id=scholar_id_filter,
    )
    selected_scholar = scholar_lookup.get(scholar_id_filter) if scholar_id_filter else None
    current_publications_url = _build_publications_url(
        mode=resolved_mode,
        scholar_profile_id=scholar_id_filter,
    )

    context = common.build_template_context(
        request,
        page_title="Publications",
        active_nav="publications",
        theme_name=resolve_theme(theme),
        session_user=common.to_session_user(current_user),
        notice=request.query_params.get("notice"),
        page_error=request.query_params.get("error"),
    )
    context["mode"] = resolved_mode
    context["publications"] = publications
    context["new_count"] = new_count
    context["total_count"] = total_count
    context["mode_new_url"] = mode_new_url
    context["mode_all_url"] = mode_all_url
    context["scholars"] = scholars
    context["selected_scholar_id"] = scholar_id_filter
    context["selected_scholar"] = selected_scholar
    context["current_publications_url"] = current_publications_url
    return common.templates.TemplateResponse(
        request=request,
        name="publications.html",
        context=context,
    )


@router.post("/publications/mark-all-read")
async def mark_all_publications_read(
    request: Request,
    return_to: str | None = Form(default=None),
    db_session: AsyncSession = Depends(get_db_session),
):
    current_user = await common.get_authenticated_user(request, db_session)
    if current_user is None:
        return common.redirect_to_login()

    updated_count = await publication_service.mark_all_unread_as_read_for_user(
        db_session,
        user_id=current_user.id,
    )
    logger.info(
        "publications.mark_all_read",
        extra={
            "event": "publications.mark_all_read",
            "user_id": current_user.id,
            "updated_count": updated_count,
        },
    )
    redirect_target = "/publications?mode=new"
    if _is_safe_return_to(return_to):
        redirect_target = return_to
    return common.redirect_with_message(
        redirect_target,
        notice=f"Marked {updated_count} publication(s) as read.",
    )
