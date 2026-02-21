from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataRepairJob, IngestionQueueItem, Publication, ScholarProfile, ScholarPublication


REPAIR_STATUS_PLANNED = "planned"
REPAIR_STATUS_RUNNING = "running"
REPAIR_STATUS_COMPLETED = "completed"
REPAIR_STATUS_FAILED = "failed"
SCOPE_MODE_SINGLE_USER = "single_user"
SCOPE_MODE_ALL_USERS = "all_users"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_scope_mode(scope_mode: str) -> str:
    normalized = scope_mode.strip().lower()
    if normalized in {SCOPE_MODE_SINGLE_USER, SCOPE_MODE_ALL_USERS}:
        return normalized
    raise ValueError("Unknown scope mode.")


def _scope_user_id(*, scope_mode: str, user_id: int | None) -> int | None:
    if scope_mode == SCOPE_MODE_SINGLE_USER:
        if user_id is None:
            raise ValueError("user_id is required when scope_mode=single_user.")
        return int(user_id)
    if user_id is not None:
        raise ValueError("user_id must be omitted when scope_mode=all_users.")
    return None


def _scope_payload(
    *,
    scope_mode: str,
    user_id: int | None,
    target_scholar_profile_ids: list[int],
    orphan_gc: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "scope_mode": scope_mode,
        "scholar_profile_ids": [int(value) for value in target_scholar_profile_ids],
        "gc_orphan_publications": bool(orphan_gc),
    }
    if user_id is not None:
        payload["user_id"] = int(user_id)
    return payload


async def _target_scholar_profile_ids(
    db_session: AsyncSession,
    *,
    scope_mode: str,
    user_id: int | None,
    scholar_profile_ids: list[int] | None,
) -> list[int]:
    stmt = select(ScholarProfile.id)
    if scope_mode == SCOPE_MODE_SINGLE_USER:
        stmt = stmt.where(ScholarProfile.user_id == user_id)
    if scholar_profile_ids:
        normalized_ids = [int(value) for value in scholar_profile_ids]
        stmt = stmt.where(ScholarProfile.id.in_(normalized_ids))
    result = await db_session.execute(stmt.order_by(ScholarProfile.id.asc()))
    ids = [int(row[0]) for row in result.all()]
    if not ids:
        raise ValueError("No target scholar profiles found for the requested scope.")
    return ids


async def _count_scope(
    db_session: AsyncSession,
    *,
    user_id: int | None,
    target_scholar_profile_ids: list[int],
) -> dict[str, int]:
    links_result = await db_session.execute(
        select(func.count())
        .select_from(ScholarPublication)
        .where(ScholarPublication.scholar_profile_id.in_(target_scholar_profile_ids))
    )
    queue_stmt = (
        select(func.count())
        .select_from(IngestionQueueItem)
        .where(IngestionQueueItem.scholar_profile_id.in_(target_scholar_profile_ids))
    )
    if user_id is not None:
        queue_stmt = queue_stmt.where(IngestionQueueItem.user_id == user_id)
    queue_result = await db_session.execute(queue_stmt)
    return {
        "target_scholar_count": len(target_scholar_profile_ids),
        "links_in_scope": int(links_result.scalar_one() or 0),
        "queue_items_in_scope": int(queue_result.scalar_one() or 0),
    }


async def _count_orphan_publications(db_session: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(Publication)
        .where(
            ~exists(
                select(1).where(ScholarPublication.publication_id == Publication.id)
            )
        )
    )
    result = await db_session.execute(stmt)
    return int(result.scalar_one() or 0)


async def _create_job(
    db_session: AsyncSession,
    *,
    requested_by: str | None,
    scope: dict[str, Any],
    dry_run: bool,
) -> DataRepairJob:
    job = DataRepairJob(
        job_name="repair_publication_links",
        requested_by=(requested_by or "").strip() or None,
        scope=scope,
        dry_run=dry_run,
        status=REPAIR_STATUS_PLANNED,
        summary={},
    )
    db_session.add(job)
    await db_session.flush()
    return job


def _job_summary(
    *,
    counts: dict[str, int],
    dry_run: bool,
    links_deleted: int,
    queue_items_deleted: int,
    scholars_reset: int,
    orphan_publications_before: int,
    orphan_publications_deleted: int,
) -> dict[str, Any]:
    return {
        **counts,
        "dry_run": bool(dry_run),
        "links_deleted": int(links_deleted),
        "queue_items_deleted": int(queue_items_deleted),
        "scholars_reset": int(scholars_reset),
        "orphan_publications_before": int(orphan_publications_before),
        "orphan_publications_deleted": int(orphan_publications_deleted),
    }


async def _delete_links_for_targets(db_session: AsyncSession, *, target_scholar_profile_ids: list[int]) -> int:
    result = await db_session.execute(
        delete(ScholarPublication).where(
            ScholarPublication.scholar_profile_id.in_(target_scholar_profile_ids)
        )
    )
    return int(result.rowcount or 0)


async def _delete_queue_for_targets(
    db_session: AsyncSession,
    *,
    user_id: int | None,
    target_scholar_profile_ids: list[int],
) -> int:
    stmt = delete(IngestionQueueItem).where(
        IngestionQueueItem.scholar_profile_id.in_(target_scholar_profile_ids)
    )
    if user_id is not None:
        stmt = stmt.where(IngestionQueueItem.user_id == user_id)
    result = await db_session.execute(stmt)
    return int(result.rowcount or 0)


async def _reset_scholar_tracking_state(
    db_session: AsyncSession,
    *,
    user_id: int | None,
    target_scholar_profile_ids: list[int],
) -> int:
    stmt = update(ScholarProfile).where(ScholarProfile.id.in_(target_scholar_profile_ids))
    if user_id is not None:
        stmt = stmt.where(ScholarProfile.user_id == user_id)
    result = await db_session.execute(
        stmt.values(
            baseline_completed=False,
            last_initial_page_fingerprint_sha256=None,
            last_initial_page_checked_at=None,
            last_run_dt=None,
            last_run_status=None,
        )
    )
    return int(result.rowcount or 0)


async def _delete_orphan_publications(db_session: AsyncSession) -> int:
    result = await db_session.execute(
        delete(Publication).where(
            ~exists(select(1).where(ScholarPublication.publication_id == Publication.id))
        )
    )
    return int(result.rowcount or 0)


async def _mutation_counts(
    db_session: AsyncSession,
    *,
    user_id: int | None,
    target_ids: list[int],
    dry_run: bool,
    gc_orphan_publications: bool,
) -> tuple[int, int, int, int]:
    if dry_run:
        return 0, 0, 0, 0
    links_deleted = await _delete_links_for_targets(
        db_session,
        target_scholar_profile_ids=target_ids,
    )
    queue_deleted = await _delete_queue_for_targets(
        db_session,
        user_id=user_id,
        target_scholar_profile_ids=target_ids,
    )
    scholars_reset = await _reset_scholar_tracking_state(
        db_session,
        user_id=user_id,
        target_scholar_profile_ids=target_ids,
    )
    orphan_deleted = 0
    if gc_orphan_publications:
        orphan_deleted = await _delete_orphan_publications(db_session)
    return links_deleted, queue_deleted, scholars_reset, orphan_deleted


def _result_payload(*, job: DataRepairJob, scope: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": int(job.id),
        "status": job.status,
        "scope": scope,
        "summary": summary,
    }


async def _complete_job(
    db_session: AsyncSession,
    *,
    job: DataRepairJob,
    summary: dict[str, Any],
    scope: dict[str, Any],
) -> dict[str, Any]:
    job.summary = summary
    job.status = REPAIR_STATUS_COMPLETED
    job.finished_at = _utcnow()
    await db_session.commit()
    return _result_payload(job=job, scope=scope, summary=summary)


async def _fail_job(db_session: AsyncSession, *, job: DataRepairJob, error: Exception) -> None:
    await db_session.rollback()
    job.status = REPAIR_STATUS_FAILED
    job.error_text = str(error)
    job.finished_at = _utcnow()
    db_session.add(job)
    await db_session.commit()


async def _prepare_repair_job(
    db_session: AsyncSession,
    *,
    scope_mode: str,
    user_id: int | None,
    scholar_profile_ids: list[int] | None,
    dry_run: bool,
    gc_orphan_publications: bool,
    requested_by: str | None,
) -> tuple[int | None, list[int], dict[str, Any], DataRepairJob]:
    normalized_scope = _normalize_scope_mode(scope_mode)
    scope_user_id = _scope_user_id(scope_mode=normalized_scope, user_id=user_id)
    target_ids = await _target_scholar_profile_ids(
        db_session,
        scope_mode=normalized_scope,
        user_id=scope_user_id,
        scholar_profile_ids=scholar_profile_ids,
    )
    scope = _scope_payload(
        scope_mode=normalized_scope,
        user_id=scope_user_id,
        target_scholar_profile_ids=target_ids,
        orphan_gc=gc_orphan_publications,
    )
    job = await _create_job(db_session, requested_by=requested_by, scope=scope, dry_run=dry_run)
    job.status = REPAIR_STATUS_RUNNING
    job.started_at = _utcnow()
    return scope_user_id, target_ids, scope, job


async def _build_repair_summary(
    db_session: AsyncSession,
    *,
    scope_user_id: int | None,
    target_ids: list[int],
    dry_run: bool,
    gc_orphan_publications: bool,
) -> dict[str, Any]:
    counts = await _count_scope(db_session, user_id=scope_user_id, target_scholar_profile_ids=target_ids)
    orphan_before = await _count_orphan_publications(db_session)
    links_deleted, queue_deleted, scholars_reset, orphan_deleted = await _mutation_counts(
        db_session,
        user_id=scope_user_id,
        target_ids=target_ids,
        dry_run=dry_run,
        gc_orphan_publications=gc_orphan_publications,
    )
    return _job_summary(
        counts=counts,
        dry_run=dry_run,
        links_deleted=links_deleted,
        queue_items_deleted=queue_deleted,
        scholars_reset=scholars_reset,
        orphan_publications_before=orphan_before,
        orphan_publications_deleted=orphan_deleted,
    )


async def run_publication_link_repair(
    db_session: AsyncSession,
    *,
    scope_mode: str = SCOPE_MODE_SINGLE_USER,
    user_id: int | None = None,
    scholar_profile_ids: list[int] | None = None,
    dry_run: bool = True,
    gc_orphan_publications: bool = False,
    requested_by: str | None = None,
) -> dict[str, Any]:
    scope_user_id, target_ids, scope, job = await _prepare_repair_job(
        db_session,
        scope_mode=scope_mode,
        user_id=user_id,
        scholar_profile_ids=scholar_profile_ids,
        dry_run=dry_run,
        gc_orphan_publications=gc_orphan_publications,
        requested_by=requested_by,
    )

    try:
        summary = await _build_repair_summary(
            db_session,
            scope_user_id=scope_user_id,
            target_ids=target_ids,
            dry_run=dry_run,
            gc_orphan_publications=gc_orphan_publications,
        )
        return await _complete_job(db_session, job=job, summary=summary, scope=scope)
    except Exception as exc:
        await _fail_job(db_session, job=job, error=exc)
        raise
