from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_current_user
from app.api.errors import ApiException
from app.api.responses import success_payload
from app.api.schemas import (
    MarkAllReadEnvelope,
    MarkSelectedReadEnvelope,
    MarkSelectedReadRequest,
    PublicationsListEnvelope,
    RetryPublicationPdfEnvelope,
    RetryPublicationPdfRequest,
)
from app.db.models import User
from app.db.session import get_db_session
from app.services.domains.publications import application as publication_service
from app.services.domains.scholars import application as scholar_service
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/publications", tags=["api-publications"])


async def _require_selected_profile(
    db_session: AsyncSession,
    *,
    user_id: int,
    selected_scholar_id: int | None,
) -> None:
    if selected_scholar_id is None:
        return
    selected_profile = await scholar_service.get_user_scholar_by_id(
        db_session,
        user_id=user_id,
        scholar_profile_id=selected_scholar_id,
    )
    if selected_profile is None:
        raise ApiException(
            status_code=404,
            code="scholar_not_found",
            message="Scholar filter not found.",
        )


def _serialize_publication_item(item) -> dict[str, object]:
    return {
        "publication_id": item.publication_id,
        "scholar_profile_id": item.scholar_profile_id,
        "scholar_label": item.scholar_label,
        "title": item.title,
        "year": item.year,
        "citation_count": item.citation_count,
        "venue_text": item.venue_text,
        "pub_url": item.pub_url,
        "doi": item.doi,
        "pdf_url": item.pdf_url,
        "is_read": item.is_read,
        "first_seen_at": item.first_seen_at,
        "is_new_in_latest_run": item.is_new_in_latest_run,
    }


async def _publication_counts(
    db_session: AsyncSession,
    *,
    user_id: int,
    selected_scholar_id: int | None,
) -> tuple[int, int, int]:
    unread_count = await publication_service.count_unread_for_user(
        db_session,
        user_id=user_id,
        scholar_profile_id=selected_scholar_id,
    )
    latest_count = await publication_service.count_latest_for_user(
        db_session,
        user_id=user_id,
        scholar_profile_id=selected_scholar_id,
    )
    total_count = await publication_service.count_for_user(
        db_session,
        user_id=user_id,
        mode=publication_service.MODE_ALL,
        scholar_profile_id=selected_scholar_id,
    )
    return unread_count, latest_count, total_count


def _publications_list_data(
    *,
    mode: str,
    selected_scholar_id: int | None,
    unread_count: int,
    latest_count: int,
    total_count: int,
    publications: list,
) -> dict[str, object]:
    return {
        "mode": mode,
        "selected_scholar_profile_id": selected_scholar_id,
        "unread_count": unread_count,
        "latest_count": latest_count,
        "new_count": latest_count,
        "total_count": total_count,
        "publications": [_serialize_publication_item(item) for item in publications],
    }


@router.get(
    "",
    response_model=PublicationsListEnvelope,
)
async def list_publications(
    request: Request,
    mode: Literal["all", "unread", "latest", "new"] | None = Query(default=None),
    scholar_profile_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=300, ge=1, le=1000),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    resolved_mode = publication_service.resolve_publication_view_mode(mode)
    selected_scholar_id = scholar_profile_id
    await _require_selected_profile(
        db_session,
        user_id=current_user.id,
        selected_scholar_id=selected_scholar_id,
    )

    publications = await publication_service.list_for_user(
        db_session,
        user_id=current_user.id,
        mode=resolved_mode,
        scholar_profile_id=selected_scholar_id,
        limit=limit,
    )
    await publication_service.schedule_missing_pdf_enrichment_for_user(
        user_id=current_user.id,
        request_email=current_user.email,
        items=publications,
        max_items=settings.unpaywall_max_items_per_request,
    )
    unread_count, latest_count, total_count = await _publication_counts(
        db_session,
        user_id=current_user.id,
        selected_scholar_id=selected_scholar_id,
    )
    data = _publications_list_data(
        mode=resolved_mode,
        selected_scholar_id=selected_scholar_id,
        unread_count=unread_count,
        latest_count=latest_count,
        total_count=total_count,
        publications=publications,
    )
    return success_payload(request, data=data)


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


@router.post(
    "/{publication_id}/retry-pdf",
    response_model=RetryPublicationPdfEnvelope,
)
async def retry_publication_pdf(
    payload: RetryPublicationPdfRequest,
    request: Request,
    publication_id: int = Path(ge=1),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    publication = await publication_service.retry_pdf_for_user(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=payload.scholar_profile_id,
        publication_id=publication_id,
        unpaywall_email=current_user.email,
    )
    if publication is None:
        raise ApiException(
            status_code=404,
            code="publication_not_found",
            message="Publication not found.",
        )
    resolved_pdf = bool(publication.pdf_url)
    logger.info(
        "api.publications.retry_pdf",
        extra={
            "event": "api.publications.retry_pdf",
            "user_id": current_user.id,
            "scholar_profile_id": payload.scholar_profile_id,
            "publication_id": publication_id,
            "resolved_pdf": resolved_pdf,
            "has_doi": bool(publication.doi),
        },
    )
    message = "Open-access PDF link resolved." if resolved_pdf else "No open-access PDF link found."
    return success_payload(
        request,
        data={
            "message": message,
            "resolved_pdf": resolved_pdf,
            "publication": _serialize_publication_item(publication),
        },
    )
