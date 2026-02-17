from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_current_user
from app.api.errors import ApiException
from app.api.responses import success_payload
from app.api.schemas import (
    MarkAllReadEnvelope,
    MarkSelectedReadEnvelope,
    MarkSelectedReadRequest,
    PublicationsListEnvelope,
)
from app.db.models import User
from app.db.session import get_db_session
from app.services import publications as publication_service
from app.services import scholars as scholar_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/publications", tags=["api-publications"])


@router.get(
    "",
    response_model=PublicationsListEnvelope,
)
async def list_publications(
    request: Request,
    mode: Literal["all", "new"] | None = Query(default=None),
    scholar_profile_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=300, ge=1, le=1000),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    resolved_mode = publication_service.resolve_mode(mode)
    selected_scholar_id = scholar_profile_id
    if selected_scholar_id is not None:
        selected_profile = await scholar_service.get_user_scholar_by_id(
            db_session,
            user_id=current_user.id,
            scholar_profile_id=selected_scholar_id,
        )
        if selected_profile is None:
            raise ApiException(
                status_code=404,
                code="scholar_not_found",
                message="Scholar filter not found.",
            )

    publications = await publication_service.list_for_user(
        db_session,
        user_id=current_user.id,
        mode=resolved_mode,
        scholar_profile_id=selected_scholar_id,
        limit=limit,
    )
    new_count = await publication_service.count_for_user(
        db_session,
        user_id=current_user.id,
        mode=publication_service.MODE_NEW,
        scholar_profile_id=selected_scholar_id,
    )
    total_count = await publication_service.count_for_user(
        db_session,
        user_id=current_user.id,
        mode=publication_service.MODE_ALL,
        scholar_profile_id=selected_scholar_id,
    )
    return success_payload(
        request,
        data={
            "mode": resolved_mode,
            "selected_scholar_profile_id": selected_scholar_id,
            "new_count": new_count,
            "total_count": total_count,
            "publications": [
                {
                    "publication_id": item.publication_id,
                    "scholar_profile_id": item.scholar_profile_id,
                    "scholar_label": item.scholar_label,
                    "title": item.title,
                    "year": item.year,
                    "citation_count": item.citation_count,
                    "venue_text": item.venue_text,
                    "pub_url": item.pub_url,
                    "is_read": item.is_read,
                    "first_seen_at": item.first_seen_at,
                    "is_new_in_latest_run": item.is_new_in_latest_run,
                }
                for item in publications
            ],
        },
    )


@router.post(
    "/mark-all-read",
    response_model=MarkAllReadEnvelope,
)
async def mark_all_publications_read(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    updated_count = await publication_service.mark_all_unread_as_read_for_user(
        db_session,
        user_id=current_user.id,
    )
    logger.info(
        "api.publications.mark_all_read",
        extra={
            "event": "api.publications.mark_all_read",
            "user_id": current_user.id,
            "updated_count": updated_count,
        },
    )
    return success_payload(
        request,
        data={
            "message": "Marked all unread publications as read.",
            "updated_count": updated_count,
        },
    )


@router.post(
    "/mark-read",
    response_model=MarkSelectedReadEnvelope,
)
async def mark_selected_publications_read(
    payload: MarkSelectedReadRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    selection_pairs = sorted(
        {
            (int(item.scholar_profile_id), int(item.publication_id))
            for item in payload.selections
        }
    )
    updated_count = await publication_service.mark_selected_as_read_for_user(
        db_session,
        user_id=current_user.id,
        selections=selection_pairs,
    )
    logger.info(
        "api.publications.mark_selected_read",
        extra={
            "event": "api.publications.mark_selected_read",
            "user_id": current_user.id,
            "requested_count": len(selection_pairs),
            "updated_count": updated_count,
        },
    )
    return success_payload(
        request,
        data={
            "message": "Marked selected publications as read.",
            "requested_count": len(selection_pairs),
            "updated_count": updated_count,
        },
    )
