from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.services.publications.types import PublicationListItem
from tests.integration.helpers import (
    api_csrf_headers,
    insert_user,
    login_user,
)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_publications_list_schedules_background_enrichment(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-pubs-bg@example.com",
        password="api-password",
    )
    scholar_result = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, true)
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "background111",
            "display_name": "Background Scholar",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())
    publication_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 3)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 17):064x}",
            "title_raw": "Background Target",
            "title_normalized": "background target",
        },
    )
    publication_id = int(publication_result.scalar_one())
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
    await db_session.commit()

    async def _fake_schedule(db_session, *, user_id: int, request_email: str | None, items, max_items: int):
        assert db_session is not None
        assert user_id > 0
        assert request_email == "api-pubs-bg@example.com"
        assert int(max_items) > 0
        assert any(int(item.publication_id) == publication_id for item in items)
        return 1

    monkeypatch.setattr(
        "app.services.publications.application.schedule_missing_pdf_enrichment_for_user",
        _fake_schedule,
    )

    client = TestClient(app)
    login_user(client, email="api-pubs-bg@example.com", password="api-password")

    response = client.get("/api/v1/publications?mode=all")
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["publications"]) == 1
    assert int(data["publications"][0]["publication_id"]) == publication_id
    assert data["publications"][0]["pdf_url"] is None
    assert data["publications"][0]["pdf_status"] in {"untracked", "queued", "running", "failed"}


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_publication_retry_pdf_queues_resolution_job(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-pubs-retry@example.com",
        password="api-password",
    )
    scholar_result = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, true)
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "retryScholar01",
            "display_name": "Retry Scholar",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())
    publication_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 7)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 9):064x}",
            "title_raw": "Retry Target",
            "title_normalized": "retry target",
        },
    )
    publication_id = int(publication_result.scalar_one())
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
    await db_session.commit()

    async def _fake_retry_scheduler(db_session, *, user_id: int, request_email: str | None, item: PublicationListItem):
        assert db_session is not None
        assert user_id > 0
        assert request_email == "api-pubs-retry@example.com"
        assert int(item.publication_id) == publication_id
        return True

    monkeypatch.setattr(
        "app.services.publications.application.schedule_retry_pdf_enrichment_for_row",
        _fake_retry_scheduler,
    )

    async def _fake_hydrate(db_session, *, items: list[PublicationListItem]):
        assert db_session is not None
        assert len(items) == 1
        item = items[0]
        return [
            PublicationListItem(
                publication_id=item.publication_id,
                scholar_profile_id=item.scholar_profile_id,
                scholar_label=item.scholar_label,
                title=item.title,
                year=item.year,
                citation_count=item.citation_count,
                venue_text=item.venue_text,
                pub_url=item.pub_url,
                pdf_url=item.pdf_url,
                is_read=item.is_read,
                first_seen_at=item.first_seen_at,
                is_new_in_latest_run=item.is_new_in_latest_run,
                pdf_status="queued",
                pdf_attempt_count=1,
                pdf_failure_reason="no_pdf_found",
                pdf_failure_detail="no_pdf_found",
            )
        ]

    monkeypatch.setattr(
        "app.services.publications.application.hydrate_pdf_enrichment_state",
        _fake_hydrate,
    )

    client = TestClient(app)
    login_user(client, email="api-pubs-retry@example.com", password="api-password")
    headers = api_csrf_headers(client)

    response = client.post(
        f"/api/v1/publications/{publication_id}/retry-pdf",
        json={"scholar_profile_id": scholar_profile_id},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["queued"] is True
    assert payload["resolved_pdf"] is False
    assert payload["publication"]["publication_id"] == publication_id
    assert payload["publication"]["pdf_url"] is None
    assert payload["publication"]["pdf_status"] == "queued"
    assert payload["publication"]["pdf_attempt_count"] == 1
    assert payload["publication"]["pdf_failure_reason"] == "no_pdf_found"

    stored = await db_session.execute(
        text("SELECT pdf_url FROM publications WHERE id = :publication_id"),
        {"publication_id": publication_id},
    )
    stored_pdf_url = stored.scalar_one()
    assert stored_pdf_url is None


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_publications_unread_and_latest_modes_can_diverge(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-pubs-mismatch@example.com",
        password="api-password",
    )
    scholar_result = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, true)
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "mismatchScholar01",
            "display_name": "Mismatch Scholar",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())

    older_run_result = await db_session.execute(
        text(
            """
            INSERT INTO crawl_runs (user_id, trigger_type, status, scholar_count, new_pub_count)
            VALUES (:user_id, 'manual', 'success', 1, 1)
            RETURNING id
            """
        ),
        {"user_id": user_id},
    )
    older_run_id = int(older_run_result.scalar_one())

    latest_run_result = await db_session.execute(
        text(
            """
            INSERT INTO crawl_runs (user_id, trigger_type, status, scholar_count, new_pub_count)
            VALUES (:user_id, 'scheduled', 'success', 1, 0)
            RETURNING id
            """
        ),
        {"user_id": user_id},
    )
    latest_run_id = int(latest_run_result.scalar_one())
    assert latest_run_id > older_run_id

    publication_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 12)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 99):064x}",
            "title_raw": "Unread But Not Latest",
            "title_normalized": "unread but not latest",
        },
    )
    publication_id = int(publication_result.scalar_one())

    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (
                scholar_profile_id,
                publication_id,
                is_read,
                first_seen_run_id
            )
            VALUES (:scholar_profile_id, :publication_id, false, :first_seen_run_id)
            """
        ),
        {
            "scholar_profile_id": scholar_profile_id,
            "publication_id": publication_id,
            "first_seen_run_id": older_run_id,
        },
    )
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="api-pubs-mismatch@example.com", password="api-password")

    unread_response = client.get("/api/v1/publications?mode=unread")
    assert unread_response.status_code == 200
    unread_data = unread_response.json()["data"]
    assert unread_data["mode"] == "unread"
    assert unread_data["unread_count"] == 1
    assert unread_data["latest_count"] == 0
    assert unread_data["new_count"] == 0
    assert len(unread_data["publications"]) == 1
    assert int(unread_data["publications"][0]["publication_id"]) == publication_id
    assert unread_data["publications"][0]["is_new_in_latest_run"] is False

    latest_response = client.get("/api/v1/publications?mode=latest")
    assert latest_response.status_code == 200
    latest_data = latest_response.json()["data"]
    assert latest_data["mode"] == "latest"
    assert latest_data["latest_count"] == 0
    assert len(latest_data["publications"]) == 0

    alias_response = client.get("/api/v1/publications?mode=new")
    assert alias_response.status_code == 200
    alias_data = alias_response.json()["data"]
    assert alias_data["mode"] == "latest"
    assert alias_data["latest_count"] == latest_data["latest_count"]
    assert alias_data["publications"] == latest_data["publications"]
