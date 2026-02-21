from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Publication

INTEGRITY_CHECK_DEFS = (
    (
        "legacy_cluster_id_format",
        "warning",
        "Publications with non-namespaced cluster IDs.",
    ),
    (
        "negative_citation_count",
        "failure",
        "Publications with negative citation counts.",
    ),
    (
        "orphan_publications",
        "warning",
        "Publications with no scholar links.",
    ),
    (
        "orphan_scholar_publication_links",
        "failure",
        "Link rows missing parent scholar/publication.",
    ),
    (
        "duplicate_fingerprint_keys",
        "failure",
        "Duplicate publication fingerprint keys.",
    ),
    (
        "duplicate_cluster_ids",
        "failure",
        "Duplicate non-null publication cluster IDs.",
    ),
    (
        "missing_pdf_url",
        "metric",
        "Publications without a resolved PDF URL.",
    ),
)


async def _legacy_cluster_id_count(db_session: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(Publication)
        .where(Publication.cluster_id.is_not(None))
        .where(~Publication.cluster_id.like("cfv:%"))
        .where(~Publication.cluster_id.like("cluster:%"))
    )
    result = await db_session.execute(stmt)
    return int(result.scalar_one() or 0)


async def _negative_citation_count(db_session: AsyncSession) -> int:
    result = await db_session.execute(
        select(func.count()).select_from(Publication).where(Publication.citation_count < 0)
    )
    return int(result.scalar_one() or 0)


async def _missing_pdf_url_count(db_session: AsyncSession) -> int:
    result = await db_session.execute(
        select(func.count()).select_from(Publication).where(Publication.pdf_url.is_(None))
    )
    return int(result.scalar_one() or 0)


async def _count_from_sql(db_session: AsyncSession, *, sql: str) -> int:
    result = await db_session.execute(text(sql))
    return int(result.scalar_one() or 0)


def _issues_for_severity(*, checks: list[dict[str, Any]], severity: str) -> list[str]:
    return [row["name"] for row in checks if row["severity"] == severity and row["count"] > 0]


def _check_row(*, name: str, count: int, severity: str, message: str) -> dict[str, Any]:
    return {
        "name": name,
        "count": int(count),
        "severity": severity,
        "message": message,
    }


async def _collect_counts(db_session: AsyncSession) -> dict[str, int]:
    orphan_publications = await _count_from_sql(
        db_session,
        sql=(
            "SELECT count(*) FROM publications p "
            "LEFT JOIN scholar_publications sp ON sp.publication_id = p.id "
            "WHERE sp.publication_id IS NULL"
        ),
    )
    orphan_links = await _count_from_sql(
        db_session,
        sql=(
            "SELECT count(*) FROM scholar_publications sp "
            "LEFT JOIN publications p ON p.id = sp.publication_id "
            "LEFT JOIN scholar_profiles s ON s.id = sp.scholar_profile_id "
            "WHERE p.id IS NULL OR s.id IS NULL"
        ),
    )
    duplicate_fingerprints = await _count_from_sql(
        db_session,
        sql=(
            "SELECT count(*) FROM ("
            "SELECT fingerprint_sha256 FROM publications "
            "GROUP BY fingerprint_sha256 HAVING count(*) > 1"
            ") dup"
        ),
    )
    duplicate_cluster_ids = await _count_from_sql(
        db_session,
        sql=(
            "SELECT count(*) FROM ("
            "SELECT cluster_id FROM publications "
            "WHERE cluster_id IS NOT NULL "
            "GROUP BY cluster_id HAVING count(*) > 1"
            ") dup"
        ),
    )
    return {
        "legacy_cluster_id_format": await _legacy_cluster_id_count(db_session),
        "negative_citation_count": await _negative_citation_count(db_session),
        "orphan_publications": orphan_publications,
        "orphan_scholar_publication_links": orphan_links,
        "duplicate_fingerprint_keys": duplicate_fingerprints,
        "duplicate_cluster_ids": duplicate_cluster_ids,
        "missing_pdf_url": await _missing_pdf_url_count(db_session),
    }


def _build_checks(*, counts: dict[str, int]) -> list[dict[str, Any]]:
    return [
        _check_row(
            name=name,
            count=counts[name],
            severity=severity,
            message=message,
        )
        for name, severity, message in INTEGRITY_CHECK_DEFS
    ]


def _status_from_issues(*, failures: list[str], warnings: list[str]) -> str:
    status = "ok"
    if failures:
        status = "failed"
    elif warnings:
        status = "warning"
    return status


async def collect_integrity_report(db_session: AsyncSession) -> dict[str, Any]:
    counts = await _collect_counts(db_session)
    checks = _build_checks(counts=counts)
    failures = _issues_for_severity(checks=checks, severity="failure")
    warnings = _issues_for_severity(checks=checks, severity="warning")

    return {
        "status": _status_from_issues(failures=failures, warnings=warnings),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "failures": failures,
        "warnings": warnings,
        "checks": checks,
    }
