from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.domains.dbops import run_publication_link_repair
from tests.integration.helpers import insert_user


async def _insert_scholar_profile(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_id: str,
    display_name: str,
    baseline_completed: bool = False,
) -> int:
    result = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled, baseline_completed)
            VALUES (:user_id, :scholar_id, :display_name, true, :baseline_completed)
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": scholar_id,
            "display_name": display_name,
            "baseline_completed": baseline_completed,
        },
    )
    return int(result.scalar_one())


async def _insert_publication(
    db_session: AsyncSession,
    *,
    fingerprint: str,
    title_raw: str,
    title_normalized: str,
    citation_count: int,
) -> int:
    result = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, :citation_count)
            RETURNING id
            """
        ),
        {
            "fingerprint": fingerprint,
            "title_raw": title_raw,
            "title_normalized": title_normalized,
            "citation_count": citation_count,
        },
    )
    return int(result.scalar_one())


async def _insert_scholar_publication_link(
    db_session: AsyncSession,
    *,
    scholar_profile_id: int,
    publication_id: int,
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read)
            VALUES (:scholar_profile_id, :publication_id, false)
            """
        ),
        {
            "scholar_profile_id": scholar_profile_id,
            "publication_id": publication_id,
        },
    )


async def _insert_queue_item(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholar_profile_id: int,
    reason: str,
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO ingestion_queue_items (user_id, scholar_profile_id, reason)
            VALUES (:user_id, :scholar_profile_id, :reason)
            """
        ),
        {
            "user_id": user_id,
            "scholar_profile_id": scholar_profile_id,
            "reason": reason,
        },
    )


async def _count_rows(
    db_session: AsyncSession,
    *,
    sql: str,
    params: dict[str, int],
) -> int:
    result = await db_session.execute(text(sql), params)
    return int(result.scalar_one())


async def _seed_apply_case(db_session: AsyncSession, *, user_id: int) -> tuple[int, int]:
    scholar_profile_id = await _insert_scholar_profile(
        db_session,
        user_id=user_id,
        scholar_id="repairApply01",
        display_name="Repair Apply",
        baseline_completed=True,
    )
    publication_id = await _insert_publication(
        db_session,
        fingerprint=f"{(user_id + 1):064x}",
        title_raw="Repair Apply Paper",
        title_normalized="repair apply paper",
        citation_count=9,
    )
    await _insert_scholar_publication_link(
        db_session,
        scholar_profile_id=scholar_profile_id,
        publication_id=publication_id,
    )
    await _insert_queue_item(
        db_session,
        user_id=user_id,
        scholar_profile_id=scholar_profile_id,
        reason="manual_repair_test",
    )
    await db_session.commit()
    return scholar_profile_id, publication_id


async def _assert_apply_effects(
    db_session: AsyncSession,
    *,
    scholar_profile_id: int,
    publication_id: int,
) -> None:
    links_count = await _count_rows(
        db_session,
        sql="SELECT count(*) FROM scholar_publications WHERE scholar_profile_id = :scholar_profile_id",
        params={"scholar_profile_id": scholar_profile_id},
    )
    queue_count = await _count_rows(
        db_session,
        sql="SELECT count(*) FROM ingestion_queue_items WHERE scholar_profile_id = :scholar_profile_id",
        params={"scholar_profile_id": scholar_profile_id},
    )
    baseline_completed = await _count_rows(
        db_session,
        sql=(
            "SELECT count(*) FROM scholar_profiles "
            "WHERE id = :scholar_profile_id AND baseline_completed = false"
        ),
        params={"scholar_profile_id": scholar_profile_id},
    )
    publication_count = await _count_rows(
        db_session,
        sql="SELECT count(*) FROM publications WHERE id = :publication_id",
        params={"publication_id": publication_id},
    )
    assert links_count == 0
    assert queue_count == 0
    assert baseline_completed == 1
    assert publication_count == 0


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_publication_link_repair_dry_run_records_job_without_mutation(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(db_session, email="repair-dry@example.com", password="api-password")
    scholar_profile_id = await _insert_scholar_profile(
        db_session,
        user_id=user_id,
        scholar_id="repairDry001",
        display_name="Repair Dry",
    )
    publication_id = await _insert_publication(
        db_session,
        fingerprint=f"{user_id:064x}",
        title_raw="Repair Dry Paper",
        title_normalized="repair dry paper",
        citation_count=1,
    )
    await _insert_scholar_publication_link(
        db_session,
        scholar_profile_id=scholar_profile_id,
        publication_id=publication_id,
    )
    await db_session.commit()

    result = await run_publication_link_repair(
        db_session,
        user_id=user_id,
        dry_run=True,
        requested_by="test-suite",
    )

    assert result["status"] == "completed"
    assert bool(result["summary"]["dry_run"]) is True
    assert int(result["summary"]["links_deleted"]) == 0

    links_count = await _count_rows(
        db_session,
        sql="SELECT count(*) FROM scholar_publications WHERE scholar_profile_id = :scholar_profile_id",
        params={"scholar_profile_id": scholar_profile_id},
    )
    assert links_count == 1


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_publication_link_repair_apply_clears_links_and_can_gc_orphans(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(db_session, email="repair-apply@example.com", password="api-password")
    scholar_profile_id, publication_id = await _seed_apply_case(db_session, user_id=user_id)

    result = await run_publication_link_repair(
        db_session,
        user_id=user_id,
        dry_run=False,
        gc_orphan_publications=True,
        requested_by="test-suite",
    )

    assert result["status"] == "completed"
    assert bool(result["summary"]["dry_run"]) is False
    assert int(result["summary"]["links_deleted"]) == 1
    assert int(result["summary"]["queue_items_deleted"]) == 1
    assert int(result["summary"]["scholars_reset"]) == 1
    await _assert_apply_effects(
        db_session,
        scholar_profile_id=scholar_profile_id,
        publication_id=publication_id,
    )
