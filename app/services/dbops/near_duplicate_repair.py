from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DataRepairJob
from app.services.dbops.application import (
    REPAIR_STATUS_COMPLETED,
    REPAIR_STATUS_FAILED,
    REPAIR_STATUS_PLANNED,
    REPAIR_STATUS_RUNNING,
)
from app.services.publications import dedup as dedup_service

NEAR_DUP_JOB_NAME = "repair_publication_near_duplicates"
NEAR_DUP_DEFAULT_MAX_CLUSTERS = 25


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalized_cluster_keys(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        key = str(value or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


def _normalized_max_clusters(value: int) -> int:
    return max(1, min(int(value), 200))


def _scope_payload(
    *,
    similarity_threshold: float,
    min_shared_tokens: int,
    max_year_delta: int,
    max_clusters: int,
    selected_cluster_keys: list[str],
) -> dict[str, Any]:
    return {
        "similarity_threshold": float(similarity_threshold),
        "min_shared_tokens": int(min_shared_tokens),
        "max_year_delta": int(max_year_delta),
        "max_clusters": int(max_clusters),
        "selected_cluster_keys": selected_cluster_keys,
    }


async def _create_job(
    db_session: AsyncSession,
    *,
    requested_by: str | None,
    scope: dict[str, Any],
    dry_run: bool,
) -> DataRepairJob:
    job = DataRepairJob(
        job_name=NEAR_DUP_JOB_NAME,
        requested_by=(requested_by or "").strip() or None,
        scope=scope,
        dry_run=bool(dry_run),
        status=REPAIR_STATUS_PLANNED,
        summary={},
    )
    db_session.add(job)
    await db_session.flush()
    job.status = REPAIR_STATUS_RUNNING
    job.started_at = _utcnow()
    return job


def _selected_clusters(
    *,
    clusters: list[dedup_service.NearDuplicateCluster],
    selected_cluster_keys: list[str],
) -> tuple[list[dedup_service.NearDuplicateCluster], list[str]]:
    if not selected_cluster_keys:
        return [], []
    by_key = {cluster.cluster_key.lower(): cluster for cluster in clusters}
    selected: list[dedup_service.NearDuplicateCluster] = []
    missing: list[str] = []
    for key in selected_cluster_keys:
        cluster = by_key.get(key)
        if cluster is None:
            missing.append(key)
            continue
        selected.append(cluster)
    return selected, missing


async def _merge_selected_clusters(
    db_session: AsyncSession,
    *,
    selected_clusters: list[dedup_service.NearDuplicateCluster],
) -> int:
    merged_publications = 0
    for cluster in selected_clusters:
        merged_publications += await dedup_service.merge_near_duplicate_cluster(
            db_session,
            cluster=cluster,
        )
    return merged_publications


def _clusters_payload(
    *,
    clusters: list[dedup_service.NearDuplicateCluster],
    max_clusters: int,
) -> list[dict[str, object]]:
    preview = clusters[:max_clusters]
    return [dedup_service.near_duplicate_cluster_payload(cluster) for cluster in preview]


def _summary_payload(
    *,
    dry_run: bool,
    cluster_count: int,
    selected_count: int,
    missing_count: int,
    merged_publications: int,
    max_clusters: int,
) -> dict[str, Any]:
    return {
        "dry_run": bool(dry_run),
        "candidate_cluster_count": int(cluster_count),
        "selected_cluster_count": int(selected_count),
        "missing_selected_cluster_count": int(missing_count),
        "merged_publications": int(merged_publications),
        "preview_cluster_count": int(min(cluster_count, max_clusters)),
    }


async def _complete_job(
    db_session: AsyncSession,
    *,
    job: DataRepairJob,
    scope: dict[str, Any],
    summary: dict[str, Any],
    clusters: list[dict[str, object]],
) -> dict[str, Any]:
    job.status = REPAIR_STATUS_COMPLETED
    job.finished_at = _utcnow()
    job.summary = summary
    await db_session.commit()
    return {
        "job_id": int(job.id),
        "status": job.status,
        "scope": scope,
        "summary": summary,
        "clusters": clusters,
    }


async def _fail_job(db_session: AsyncSession, *, job: DataRepairJob, error: Exception) -> None:
    await db_session.rollback()
    job.status = REPAIR_STATUS_FAILED
    job.error_text = str(error)
    job.finished_at = _utcnow()
    db_session.add(job)
    await db_session.commit()


async def run_publication_near_duplicate_repair(
    db_session: AsyncSession,
    *,
    dry_run: bool = True,
    similarity_threshold: float = dedup_service.NEAR_DUP_DEFAULT_SIMILARITY_THRESHOLD,
    min_shared_tokens: int = dedup_service.NEAR_DUP_DEFAULT_MIN_SHARED_TOKENS,
    max_year_delta: int = dedup_service.NEAR_DUP_DEFAULT_MAX_YEAR_DELTA,
    max_clusters: int = NEAR_DUP_DEFAULT_MAX_CLUSTERS,
    selected_cluster_keys: list[str] | None = None,
    requested_by: str | None = None,
) -> dict[str, Any]:
    normalized_keys = _normalized_cluster_keys(selected_cluster_keys)
    bounded_clusters = _normalized_max_clusters(max_clusters)
    scope = _scope_payload(
        similarity_threshold=similarity_threshold,
        min_shared_tokens=min_shared_tokens,
        max_year_delta=max_year_delta,
        max_clusters=bounded_clusters,
        selected_cluster_keys=normalized_keys,
    )
    job = await _create_job(db_session, requested_by=requested_by, scope=scope, dry_run=dry_run)
    try:
        clusters = await dedup_service.find_near_duplicate_clusters(
            db_session,
            similarity_threshold=similarity_threshold,
            min_shared_tokens=min_shared_tokens,
            max_year_delta=max_year_delta,
        )
        selected, missing = _selected_clusters(clusters=clusters, selected_cluster_keys=normalized_keys)
        merged_publications = 0
        if not dry_run:
            if not selected:
                raise ValueError("No selected near-duplicate clusters matched current data.")
            merged_publications = await _merge_selected_clusters(db_session, selected_clusters=selected)
        preview = _clusters_payload(clusters=clusters, max_clusters=bounded_clusters)
        summary = _summary_payload(
            dry_run=dry_run,
            cluster_count=len(clusters),
            selected_count=len(selected),
            missing_count=len(missing),
            merged_publications=merged_publications,
            max_clusters=bounded_clusters,
        )
        return await _complete_job(
            db_session,
            job=job,
            scope=scope,
            summary=summary,
            clusters=preview,
        )
    except Exception as exc:
        await _fail_job(db_session, job=job, error=exc)
        raise
