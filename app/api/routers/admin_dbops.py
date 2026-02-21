from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_admin_user
from app.api.errors import ApiException
from app.api.responses import success_payload
from app.api.schemas import (
    AdminDbIntegrityEnvelope,
    AdminPdfQueueBulkEnqueueEnvelope,
    AdminPdfQueueRequeueEnvelope,
    AdminPdfQueueEnvelope,
    AdminDbRepairJobsEnvelope,
    AdminRepairPublicationLinksEnvelope,
    AdminRepairPublicationLinksRequest,
)
from app.db.models import DataRepairJob, User
from app.db.session import get_db_session
from app.services.domains.dbops import (
    collect_integrity_report,
    list_repair_jobs,
    run_publication_link_repair,
)
from app.services.domains.publications import application as publication_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/db", tags=["api-admin-dbops"])


def _serialize_repair_job(job: DataRepairJob) -> dict[str, object]:
    return {
        "id": int(job.id),
        "job_name": job.job_name,
        "requested_by": job.requested_by,
        "dry_run": bool(job.dry_run),
        "status": job.status,
        "scope": dict(job.scope or {}),
        "summary": dict(job.summary or {}),
        "error_text": job.error_text,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _requested_by_value(*, payload: AdminRepairPublicationLinksRequest, admin_user: User) -> str:
    from_payload = (payload.requested_by or "").strip()
    return from_payload or admin_user.email


def _serialize_pdf_queue_item(item) -> dict[str, object]:
    return {
        "publication_id": item.publication_id,
        "title": item.title,
        "doi": item.doi,
        "pdf_url": item.pdf_url,
        "status": item.status,
        "attempt_count": item.attempt_count,
        "last_failure_reason": item.last_failure_reason,
        "last_failure_detail": item.last_failure_detail,
        "last_source": item.last_source,
        "requested_by_user_id": item.requested_by_user_id,
        "requested_by_email": item.requested_by_email,
        "queued_at": item.queued_at,
        "last_attempt_at": item.last_attempt_at,
        "resolved_at": item.resolved_at,
        "updated_at": item.updated_at,
    }


def _requeue_response_state(*, queued: bool) -> tuple[str, str]:
    if queued:
        return "queued", "PDF lookup queued."
    return "blocked", "PDF lookup is already queued or currently running."


def _bulk_enqueue_message(*, queued_count: int, requested_count: int) -> str:
    if requested_count == 0:
        return "No missing-PDF publications were found."
    if queued_count == 0:
        return "No publications were queued; all candidates were already in-flight."
    return f"Queued {queued_count} publication(s) for PDF lookup."


def _resolve_pdf_queue_paging(
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


def _pdf_queue_page_data(*, total_count: int, page: int, page_size: int, offset: int) -> dict[str, object]:
    return {
        "total_count": int(total_count),
        "page": int(page),
        "page_size": int(page_size),
        "has_prev": int(offset) > 0,
        "has_next": int(offset) + int(page_size) < int(total_count),
    }


@router.get(
    "/integrity",
    response_model=AdminDbIntegrityEnvelope,
)
async def get_integrity_report(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(get_api_admin_user),
):
    report = await collect_integrity_report(db_session)
    logger.info(
        "api.admin.db.integrity_checked",
        extra={
            "event": "api.admin.db.integrity_checked",
            "admin_user_id": int(admin_user.id),
            "status": report.get("status"),
            "failure_count": len(report.get("failures", [])),
            "warning_count": len(report.get("warnings", [])),
        },
    )
    return success_payload(request, data=report)


@router.get(
    "/repair-jobs",
    response_model=AdminDbRepairJobsEnvelope,
)
async def get_repair_jobs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    db_session: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(get_api_admin_user),
):
    jobs = await list_repair_jobs(db_session, limit=limit)
    logger.info(
        "api.admin.db.repair_jobs_listed",
        extra={
            "event": "api.admin.db.repair_jobs_listed",
            "admin_user_id": int(admin_user.id),
            "limit": int(limit),
            "job_count": len(jobs),
        },
    )
    return success_payload(
        request,
        data={"jobs": [_serialize_repair_job(job) for job in jobs]},
    )


@router.get(
    "/pdf-queue",
    response_model=AdminPdfQueueEnvelope,
)
async def get_pdf_queue(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int | None = Query(default=None, ge=0),
    status: str | None = Query(default=None),
    db_session: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(get_api_admin_user),
):
    normalized_status = (status or "").strip().lower() or None
    resolved_page, resolved_limit, resolved_offset = _resolve_pdf_queue_paging(
        page=page,
        page_size=page_size,
        limit=limit,
        offset=offset,
    )
    queue_page = await publication_service.list_pdf_queue_page(
        db_session,
        limit=resolved_limit,
        offset=resolved_offset,
        status=normalized_status,
    )
    logger.info(
        "api.admin.db.pdf_queue_listed",
        extra={
            "event": "api.admin.db.pdf_queue_listed",
            "admin_user_id": int(admin_user.id),
            "page": int(resolved_page),
            "page_size": int(resolved_limit),
            "offset": int(resolved_offset),
            "status": normalized_status,
            "item_count": len(queue_page.items),
            "total_count": int(queue_page.total_count),
        },
    )
    return success_payload(
        request,
        data={
            "items": [_serialize_pdf_queue_item(item) for item in queue_page.items],
            **_pdf_queue_page_data(
                total_count=queue_page.total_count,
                page=resolved_page,
                page_size=resolved_limit,
                offset=resolved_offset,
            ),
        },
    )


@router.post(
    "/pdf-queue/{publication_id}/requeue",
    response_model=AdminPdfQueueRequeueEnvelope,
)
async def requeue_pdf_lookup(
    request: Request,
    publication_id: int = Path(ge=1),
    db_session: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(get_api_admin_user),
):
    result = await publication_service.enqueue_retry_pdf_job_for_publication_id(
        db_session,
        user_id=int(admin_user.id),
        request_email=admin_user.email,
        publication_id=publication_id,
    )
    if not result.publication_exists:
        raise ApiException(
            status_code=404,
            code="publication_not_found",
            message="Publication not found.",
        )
    status, message = _requeue_response_state(queued=result.queued)
    logger.info(
        "api.admin.db.pdf_queue_requeue_requested",
        extra={
            "event": "api.admin.db.pdf_queue_requeue_requested",
            "admin_user_id": int(admin_user.id),
            "publication_id": int(publication_id),
            "queued": bool(result.queued),
        },
    )
    return success_payload(
        request,
        data={
            "publication_id": int(publication_id),
            "queued": bool(result.queued),
            "status": status,
            "message": message,
        },
    )


@router.post(
    "/pdf-queue/requeue-all",
    response_model=AdminPdfQueueBulkEnqueueEnvelope,
)
async def requeue_all_missing_pdfs(
    request: Request,
    limit: int = Query(default=1000, ge=1, le=5000),
    db_session: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(get_api_admin_user),
):
    result = await publication_service.enqueue_all_missing_pdf_jobs(
        db_session,
        user_id=int(admin_user.id),
        request_email=admin_user.email,
        limit=limit,
    )
    logger.info(
        "api.admin.db.pdf_queue_requeue_all",
        extra={
            "event": "api.admin.db.pdf_queue_requeue_all",
            "admin_user_id": int(admin_user.id),
            "limit": int(limit),
            "requested_count": int(result.requested_count),
            "queued_count": int(result.queued_count),
        },
    )
    return success_payload(
        request,
        data={
            "requested_count": int(result.requested_count),
            "queued_count": int(result.queued_count),
            "message": _bulk_enqueue_message(
                queued_count=int(result.queued_count),
                requested_count=int(result.requested_count),
            ),
        },
    )


@router.post(
    "/repairs/publication-links",
    response_model=AdminRepairPublicationLinksEnvelope,
)
async def trigger_publication_link_repair(
    payload: AdminRepairPublicationLinksRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    admin_user: User = Depends(get_api_admin_user),
):
    try:
        result = await run_publication_link_repair(
            db_session,
            scope_mode=payload.scope_mode,
            user_id=payload.user_id,
            scholar_profile_ids=payload.scholar_profile_ids,
            dry_run=bool(payload.dry_run),
            gc_orphan_publications=bool(payload.gc_orphan_publications),
            requested_by=_requested_by_value(payload=payload, admin_user=admin_user),
        )
    except ValueError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_repair_scope",
            message=str(exc),
        ) from exc
    logger.info(
        "api.admin.db.publication_link_repair_triggered",
        extra={
            "event": "api.admin.db.publication_link_repair_triggered",
            "admin_user_id": int(admin_user.id),
            "scope_mode": payload.scope_mode,
            "target_user_id": int(payload.user_id) if payload.user_id is not None else None,
            "dry_run": bool(payload.dry_run),
            "gc_orphan_publications": bool(payload.gc_orphan_publications),
            "job_id": int(result["job_id"]),
            "status": result["status"],
        },
    )
    return success_payload(request, data=result)
