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
    TogglePublicationFavoriteEnvelope,
    TogglePublicationFavoriteRequest,
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
        "pdf_status": item.pdf_status,
        "pdf_attempt_count": item.pdf_attempt_count,
        "pdf_failure_reason": item.pdf_failure_reason,
        "pdf_failure_detail": item.pdf_failure_detail,
        "is_read": item.is_read,
        "is_favorite": item.is_favorite,
        "first_seen_at": item.first_seen_at,
        "is_new_in_latest_run": item.is_new_in_latest_run,
    }


async def _publication_counts(
    db_session: AsyncSession,
    *,
    user_id: int,
    selected_scholar_id: int | None,
    favorite_only: bool,
) -> tuple[int, int, int, int]:
    unread_count = await publication_service.count_unread_for_user(
        db_session,
        user_id=user_id,
        scholar_profile_id=selected_scholar_id,
        favorite_only=favorite_only,
    )
    favorites_count = await publication_service.count_favorite_for_user(
        db_session,
        user_id=user_id,
        scholar_profile_id=selected_scholar_id,
    )
    latest_count = await publication_service.count_latest_for_user(
        db_session,
        user_id=user_id,
        scholar_profile_id=selected_scholar_id,
        favorite_only=favorite_only,
    )
    total_count = await publication_service.count_for_user(
        db_session,
        user_id=user_id,
        mode=publication_service.MODE_ALL,
        scholar_profile_id=selected_scholar_id,
        favorite_only=favorite_only,
    )
    return unread_count, favorites_count, latest_count, total_count


async def _list_publications_for_request(
    db_session: AsyncSession,
    *,
    current_user: User,
    mode: Literal["all", "unread", "latest", "new"] | None,
    favorite_only: bool,
    scholar_profile_id: int | None,
    limit: int,
    offset: int,
) -> tuple[str, int | None, list]:
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
        favorite_only=favorite_only,
        limit=limit,
        offset=offset,
    )
    await publication_service.schedule_missing_pdf_enrichment_for_user(
        db_session,
        user_id=current_user.id,
        request_email=current_user.email,
        items=publications,
        max_items=settings.unpaywall_max_items_per_request,
    )
    hydrated = await publication_service.hydrate_pdf_enrichment_state(
        db_session,
        items=publications,
    )
    return resolved_mode, selected_scholar_id, hydrated


def _resolve_publications_paging(
    *,
    page: int,
    page_size: int,
    limit: int | None,
    offset: int | None,
) -> tuple[int, int, int]:
    resolved_limit = int(limit) if limit is not None else int(page_size)
    resolved_offset = int(offset) if offset is not None else max((int(page) - 1) * resolved_limit, 0)
    resolved_page = max((resolved_offset // max(resolved_limit, 1)) + 1, 1)
    return resolved_page, max(resolved_limit, 1), max(resolved_offset, 0)


def _publications_list_data(
    *,
    mode: str,
    favorite_only: bool,
    selected_scholar_id: int | None,
    unread_count: int,
    favorites_count: int,
    latest_count: int,
    total_count: int,
    publications: list,
    page: int,
    page_size: int,
    offset: int,
) -> dict[str, object]:
    return {
        "mode": mode,
        "favorite_only": favorite_only,
        "selected_scholar_profile_id": selected_scholar_id,
        "unread_count": unread_count,
        "favorites_count": favorites_count,
        "latest_count": latest_count,
        "new_count": latest_count,
        "total_count": total_count,
        "page": int(page),
        "page_size": int(page_size),
        "has_prev": int(offset) > 0,
        "has_next": int(offset) + int(page_size) < int(total_count),
        "publications": [_serialize_publication_item(item) for item in publications],
    }


def _retry_pdf_message(*, queued: bool, resolved_pdf: bool, pdf_status: str) -> str:
    if resolved_pdf:
        return "Open-access PDF link already resolved."
    if queued:
        return "PDF lookup queued."
    if pdf_status in {"queued", "running"}:
        return "PDF lookup is already queued."
    return "No open-access PDF link found."


def _favorite_message(*, is_favorite: bool) -> str:
    if is_favorite:
        return "Publication marked as favorite."
    return "Publication removed from favorites."


async def _retry_publication_state(
    db_session: AsyncSession,
    *,
    current_user: User,
    scholar_profile_id: int,
    publication_id: int,
):
    publication = await publication_service.retry_pdf_for_user(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
        publication_id=publication_id,
    )
    if publication is None:
        raise ApiException(
            status_code=404,
            code="publication_not_found",
            message="Publication not found.",
        )
    queued = False
    if not publication.pdf_url:
        queued = await publication_service.schedule_retry_pdf_enrichment_for_row(
            db_session,
            user_id=current_user.id,
            request_email=current_user.email,
            item=publication,
        )
    hydrated = await publication_service.hydrate_pdf_enrichment_state(
        db_session,
        items=[publication],
    )
    current = hydrated[0] if hydrated else publication
    return current, queued


async def _favorite_publication_state(
    db_session: AsyncSession,
    *,
    current_user: User,
    scholar_profile_id: int,
    publication_id: int,
    is_favorite: bool,
):
    updated_count = await publication_service.set_publication_favorite_for_user(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
        publication_id=publication_id,
        is_favorite=is_favorite,
    )
    if updated_count <= 0:
        raise ApiException(
            status_code=404,
            code="publication_not_found",
            message="Publication not found.",
        )
    publication = await publication_service.get_publication_item_for_user(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
        publication_id=publication_id,
    )
    if publication is None:
        raise ApiException(
            status_code=404,
            code="publication_not_found",
            message="Publication not found.",
        )
    hydrated = await publication_service.hydrate_pdf_enrichment_state(
        db_session,
        items=[publication],
    )
    return hydrated[0] if hydrated else publication


def _log_retry_pdf_result(
    *,
    current_user: User,
    scholar_profile_id: int,
    publication_id: int,
    queued: bool,
    resolved_pdf: bool,
    pdf_status: str,
    doi: str | None,
) -> None:
    logger.info(
        "api.publications.retry_pdf",
        extra={
            "event": "api.publications.retry_pdf",
            "user_id": current_user.id,
            "scholar_profile_id": scholar_profile_id,
            "publication_id": publication_id,
            "queued": queued,
            "resolved_pdf": resolved_pdf,
            "pdf_status": pdf_status,
            "has_doi": bool(doi),
        },
    )


@router.get(
    "",
    response_model=PublicationsListEnvelope,
)
async def list_publications(
    request: Request,
    mode: Literal["all", "unread", "latest", "new"] | None = Query(default=None),
    favorite_only: bool = Query(default=False),
    scholar_profile_id: int | None = Query(default=None, ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int | None = Query(default=None, ge=0),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    resolved_page, resolved_limit, resolved_offset = _resolve_publications_paging(
        page=page,
        page_size=page_size,
        limit=limit,
        offset=offset,
    )
    resolved_mode, selected_scholar_id, publications = await _list_publications_for_request(
        db_session,
        current_user=current_user,
        mode=mode,
        favorite_only=favorite_only,
        scholar_profile_id=scholar_profile_id,
        limit=resolved_limit,
        offset=resolved_offset,
    )
    unread_count, favorites_count, latest_count, total_count = await _publication_counts(
        db_session,
        user_id=current_user.id,
        selected_scholar_id=selected_scholar_id,
        favorite_only=favorite_only,
    )
    data = _publications_list_data(
        mode=resolved_mode,
        favorite_only=favorite_only,
        selected_scholar_id=selected_scholar_id,
        unread_count=unread_count,
        favorites_count=favorites_count,
        latest_count=latest_count,
        total_count=total_count,
        publications=publications,
        page=resolved_page,
        page_size=resolved_limit,
        offset=resolved_offset,
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
    current, queued = await _retry_publication_state(
        db_session,
        current_user=current_user,
        scholar_profile_id=payload.scholar_profile_id,
        publication_id=publication_id,
    )
    resolved_pdf = bool(current.pdf_url)
    message = _retry_pdf_message(
        queued=queued,
        resolved_pdf=resolved_pdf,
        pdf_status=current.pdf_status,
    )
    _log_retry_pdf_result(
        current_user=current_user,
        scholar_profile_id=payload.scholar_profile_id,
        publication_id=publication_id,
        queued=queued,
        resolved_pdf=resolved_pdf,
        pdf_status=current.pdf_status,
        doi=current.doi,
    )
    return success_payload(
        request,
        data={
            "message": message,
            "queued": queued,
            "resolved_pdf": resolved_pdf,
            "publication": _serialize_publication_item(current),
        },
    )


@router.post(
    "/{publication_id}/favorite",
    response_model=TogglePublicationFavoriteEnvelope,
)
async def toggle_publication_favorite(
    payload: TogglePublicationFavoriteRequest,
    request: Request,
    publication_id: int = Path(ge=1),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    current = await _favorite_publication_state(
        db_session,
        current_user=current_user,
        scholar_profile_id=payload.scholar_profile_id,
        publication_id=publication_id,
        is_favorite=payload.is_favorite,
    )
    logger.info(
        "api.publications.favorite",
        extra={
            "event": "api.publications.favorite",
            "user_id": current_user.id,
            "scholar_profile_id": payload.scholar_profile_id,
            "publication_id": publication_id,
            "is_favorite": bool(payload.is_favorite),
        },
    )
    return success_payload(
        request,
        data={
            "message": _favorite_message(is_favorite=bool(payload.is_favorite)),
            "publication": _serialize_publication_item(current),
        },
    )
