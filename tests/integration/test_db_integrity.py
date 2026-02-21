from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.domains.dbops.integrity import collect_integrity_report


def _check_counts(report: dict) -> dict[str, int]:
    return {row["name"]: int(row["count"]) for row in report["checks"]}


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_collect_integrity_report_ok_on_clean_database(db_session: AsyncSession) -> None:
    report = await collect_integrity_report(db_session)

    assert report["status"] == "ok"
    assert report["failures"] == []
    assert report["warnings"] == []

    check_counts = _check_counts(report)
    assert all(count == 0 for count in check_counts.values())


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_collect_integrity_report_detects_warning_and_failure(db_session: AsyncSession) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO publications (
                fingerprint_sha256,
                cluster_id,
                title_raw,
                title_normalized,
                citation_count
            )
            VALUES (
                :fingerprint_sha256,
                :cluster_id,
                :title_raw,
                :title_normalized,
                :citation_count
            )
            """
        ),
        {
            "fingerprint_sha256": f"{1:064x}",
            "cluster_id": "legacy-cluster-123",
            "title_raw": "Integrity test paper",
            "title_normalized": "integrity test paper",
            "citation_count": -5,
        },
    )
    await db_session.commit()

    report = await collect_integrity_report(db_session)
    check_counts = _check_counts(report)

    assert report["status"] == "failed"
    assert "negative_citation_count" in report["failures"]
    assert "legacy_cluster_id_format" in report["warnings"]
    assert "orphan_publications" in report["warnings"]
    assert check_counts["negative_citation_count"] == 1
    assert check_counts["legacy_cluster_id_format"] == 1
    assert check_counts["orphan_publications"] == 1
