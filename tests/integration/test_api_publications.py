from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from tests.integration.helpers import (
    api_csrf_headers,
    insert_user,
    login_user,
)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_publications_list_and_mark_read(db_session: AsyncSession) -> None:
    user_id = await insert_user(
        db_session,
        email="api-pubs@example.com",
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
            "scholar_id": "abcDEF123456",
            "display_name": "Publication Owner",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())

    publication_a = await db_session.execute(
        text(
            """
            INSERT INTO publications (
                fingerprint_sha256,
                title_raw,
                title_normalized,
                citation_count,
                pdf_url
            )
            VALUES (:fingerprint, :title_raw, :title_normalized, 10, :pdf_url)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{user_id:064x}",
            "title_raw": "Paper A",
            "title_normalized": "paper a",
            "pdf_url": "https://example.org/paper-a.pdf",
        },
    )
    publication_a_id = int(publication_a.scalar_one())

    publication_b = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 4)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 1):064x}",
            "title_raw": "Paper B",
            "title_normalized": "paper b",
        },
    )
    publication_b_id = int(publication_b.scalar_one())

    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read)
            VALUES
              (:scholar_profile_id, :publication_a_id, false),
              (:scholar_profile_id, :publication_b_id, false)
            """
        ),
        {
            "scholar_profile_id": scholar_profile_id,
            "publication_a_id": publication_a_id,
            "publication_b_id": publication_b_id,
        },
    )
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="api-pubs@example.com", password="api-password")
    headers = api_csrf_headers(client)

    list_response = client.get("/api/v1/publications?mode=all")
    assert list_response.status_code == 200
    data = list_response.json()["data"]
    assert data["mode"] == "all"
    assert data["favorite_only"] is False
    assert data["total_count"] == 2
    assert data["unread_count"] == 2
    assert data["favorites_count"] == 0
    assert data["latest_count"] == 0
    assert data["new_count"] == data["latest_count"]
    assert data["page"] == 1
    assert data["page_size"] == 100
    assert data["has_prev"] is False
    assert data["has_next"] is False
    assert isinstance(data["publications"], list)
    assert len(data["publications"]) == 2
    assert all(bool(item["is_favorite"]) is False for item in data["publications"])
    pdf_urls = {item["title"]: item["pdf_url"] for item in data["publications"]}
    assert pdf_urls["Paper A"] == "https://example.org/paper-a.pdf"
    assert pdf_urls["Paper B"] is None

    latest_response = client.get("/api/v1/publications?mode=latest")
    assert latest_response.status_code == 200
    latest_data = latest_response.json()["data"]
    assert latest_data["mode"] == "latest"
    assert latest_data["latest_count"] == 0

    unread_response = client.get("/api/v1/publications?mode=unread")
    assert unread_response.status_code == 200
    unread_data = unread_response.json()["data"]
    assert unread_data["mode"] == "unread"
    assert unread_data["unread_count"] == 2

    alias_response = client.get("/api/v1/publications?mode=new")
    assert alias_response.status_code == 200
    alias_data = alias_response.json()["data"]
    assert alias_data["mode"] == "latest"
    assert alias_data["latest_count"] == latest_data["latest_count"]
    assert alias_data["publications"] == latest_data["publications"]

    mark_selected_response = client.post(
        "/api/v1/publications/mark-read",
        json={
            "selections": [
                {
                    "scholar_profile_id": scholar_profile_id,
                    "publication_id": publication_a_id,
                }
            ]
        },
        headers=headers,
    )
    assert mark_selected_response.status_code == 200
    assert mark_selected_response.json()["data"]["requested_count"] == 1
    assert mark_selected_response.json()["data"]["updated_count"] == 1

    read_state = await db_session.execute(
        text(
            """
            SELECT publication_id, is_read
            FROM scholar_publications
            WHERE scholar_profile_id = :scholar_profile_id
            ORDER BY publication_id
            """
        ),
        {"scholar_profile_id": scholar_profile_id},
    )
    states = {int(row[0]): bool(row[1]) for row in read_state.all()}
    assert states[publication_a_id] is True
    assert states[publication_b_id] is False

    mark_response = client.post("/api/v1/publications/mark-all-read", headers=headers)
    assert mark_response.status_code == 200
    assert mark_response.json()["data"]["updated_count"] == 1


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_publications_list_supports_pagination(db_session: AsyncSession) -> None:
    user_id = await insert_user(
        db_session,
        email="api-pubs-paging@example.com",
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
            "scholar_id": "pagingScholar01",
            "display_name": "Paging Scholar",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())

    publication_ids: list[int] = []
    for index in range(3):
        created = await db_session.execute(
            text(
                """
                INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
                VALUES (:fingerprint, :title_raw, :title_normalized, 1)
                RETURNING id
                """
            ),
            {
                "fingerprint": f"{(user_id + 500 + index):064x}",
                "title_raw": f"Paged Paper {index}",
                "title_normalized": f"paged paper {index}",
            },
        )
        publication_ids.append(int(created.scalar_one()))

    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read, is_favorite)
            VALUES
              (:scholar_profile_id, :publication_1, false, false),
              (:scholar_profile_id, :publication_2, false, false),
              (:scholar_profile_id, :publication_3, false, false)
            """
        ),
        {
            "scholar_profile_id": scholar_profile_id,
            "publication_1": publication_ids[0],
            "publication_2": publication_ids[1],
            "publication_3": publication_ids[2],
        },
    )
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="api-pubs-paging@example.com", password="api-password")

    first_page = client.get("/api/v1/publications?mode=all&page=1&page_size=2")
    assert first_page.status_code == 200
    first_data = first_page.json()["data"]
    assert first_data["total_count"] == 3
    assert first_data["page"] == 1
    assert first_data["page_size"] == 2
    assert first_data["has_prev"] is False
    assert first_data["has_next"] is True
    assert len(first_data["publications"]) == 2

    second_page = client.get("/api/v1/publications?mode=all&page=2&page_size=2")
    assert second_page.status_code == 200
    second_data = second_page.json()["data"]
    assert second_data["total_count"] == 3
    assert second_data["page"] == 2
    assert second_data["page_size"] == 2
    assert second_data["has_prev"] is True
    assert second_data["has_next"] is False
    assert len(second_data["publications"]) == 1


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_publications_search_pagination_uses_filtered_total_count(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-pubs-search-page@example.com",
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
            "scholar_id": "searchPagingScholar01",
            "display_name": "Search Paging Scholar",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())
    titles = ["Alpha Optimization", "Alpha Learning", "Beta Methods"]
    publication_ids: list[int] = []
    for index, title in enumerate(titles):
        created = await db_session.execute(
            text(
                """
                INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
                VALUES (:fingerprint, :title_raw, :title_normalized, 1)
                RETURNING id
                """
            ),
            {
                "fingerprint": f"{(user_id + 900 + index):064x}",
                "title_raw": title,
                "title_normalized": title.lower(),
            },
        )
        publication_ids.append(int(created.scalar_one()))
    for publication_id in publication_ids:
        await db_session.execute(
            text(
                """
                INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read, is_favorite)
                VALUES (:scholar_profile_id, :publication_id, false, false)
                """
            ),
            {"scholar_profile_id": scholar_profile_id, "publication_id": publication_id},
        )
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="api-pubs-search-page@example.com", password="api-password")

    response = client.get("/api/v1/publications?mode=all&page=1&page_size=2&search=alpha")
    assert response.status_code == 200
    data = response.json()["data"]
    assert int(data["total_count"]) == 2
    assert data["has_next"] is False
    assert len(data["publications"]) == 2
    assert all("alpha" in str(item["title"]).lower() for item in data["publications"])


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_publications_supports_sort_by_pdf_status(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-pubs-pdf-sort@example.com",
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
            "scholar_id": "pdfSortScholar01",
            "display_name": "PDF Sort Scholar",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())

    resolved_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count, pdf_url)
            VALUES (:fingerprint, :title_raw, :title_normalized, 1, :pdf_url)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 1300):064x}",
            "title_raw": "Resolved PDF",
            "title_normalized": "resolved pdf",
            "pdf_url": "https://example.org/resolved.pdf",
        },
    )
    resolved_publication_id = int(resolved_result.scalar_one())
    queued_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 1)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 1301):064x}",
            "title_raw": "Queued PDF",
            "title_normalized": "queued pdf",
        },
    )
    queued_publication_id = int(queued_result.scalar_one())
    failed_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 1)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 1302):064x}",
            "title_raw": "Failed PDF",
            "title_normalized": "failed pdf",
        },
    )
    failed_publication_id = int(failed_result.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read, is_favorite)
            VALUES
              (:scholar_profile_id, :resolved_publication_id, false, false),
              (:scholar_profile_id, :queued_publication_id, false, false),
              (:scholar_profile_id, :failed_publication_id, false, false)
            """
        ),
        {
            "scholar_profile_id": scholar_profile_id,
            "resolved_publication_id": resolved_publication_id,
            "queued_publication_id": queued_publication_id,
            "failed_publication_id": failed_publication_id,
        },
    )
    await db_session.execute(
        text(
            """
            INSERT INTO publication_pdf_jobs (publication_id, status, attempt_count)
            VALUES (:queued_publication_id, 'queued', 1),
                   (:failed_publication_id, 'failed', 2)
            """
        ),
        {
            "queued_publication_id": queued_publication_id,
            "failed_publication_id": failed_publication_id,
        },
    )
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="api-pubs-pdf-sort@example.com", password="api-password")

    response = client.get("/api/v1/publications?mode=all&sort_by=pdf_status&sort_dir=desc")
    assert response.status_code == 200
    publications = response.json()["data"]["publications"]
    publication_ids = [int(item["publication_id"]) for item in publications]
    assert publication_ids[0] == resolved_publication_id
    assert publication_ids[-1] == failed_publication_id


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_publications_favorite_toggle_and_filter(db_session: AsyncSession) -> None:
    user_id = await insert_user(
        db_session,
        email="api-pubs-favorites@example.com",
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
            "scholar_id": "favoriteScholar01",
            "display_name": "Favorite Scholar",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())
    publication_a_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 9)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 101):064x}",
            "title_raw": "Favorite Target",
            "title_normalized": "favorite target",
        },
    )
    publication_a_id = int(publication_a_result.scalar_one())
    publication_b_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 2)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 102):064x}",
            "title_raw": "Not Favorite",
            "title_normalized": "not favorite",
        },
    )
    publication_b_id = int(publication_b_result.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read, is_favorite)
            VALUES
              (:scholar_profile_id, :publication_a_id, false, false),
              (:scholar_profile_id, :publication_b_id, false, false)
            """
        ),
        {
            "scholar_profile_id": scholar_profile_id,
            "publication_a_id": publication_a_id,
            "publication_b_id": publication_b_id,
        },
    )
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="api-pubs-favorites@example.com", password="api-password")
    headers = api_csrf_headers(client)

    set_response = client.post(
        f"/api/v1/publications/{publication_a_id}/favorite",
        json={"scholar_profile_id": scholar_profile_id, "is_favorite": True},
        headers=headers,
    )
    assert set_response.status_code == 200
    set_data = set_response.json()["data"]
    assert set_data["publication"]["publication_id"] == publication_a_id
    assert set_data["publication"]["is_favorite"] is True

    favorite_only_response = client.get("/api/v1/publications?mode=all&favorite_only=true")
    assert favorite_only_response.status_code == 200
    favorite_only_data = favorite_only_response.json()["data"]
    assert favorite_only_data["favorite_only"] is True
    assert favorite_only_data["favorites_count"] == 1
    assert favorite_only_data["total_count"] == 1
    assert len(favorite_only_data["publications"]) == 1
    assert int(favorite_only_data["publications"][0]["publication_id"]) == publication_a_id

    clear_response = client.post(
        f"/api/v1/publications/{publication_a_id}/favorite",
        json={"scholar_profile_id": scholar_profile_id, "is_favorite": False},
        headers=headers,
    )
    assert clear_response.status_code == 200
    clear_data = clear_response.json()["data"]
    assert clear_data["publication"]["publication_id"] == publication_a_id
    assert clear_data["publication"]["is_favorite"] is False

    favorite_only_after_clear_response = client.get("/api/v1/publications?mode=all&favorite_only=true")
    assert favorite_only_after_clear_response.status_code == 200
    favorite_only_after_clear_data = favorite_only_after_clear_response.json()["data"]
    assert favorite_only_after_clear_data["favorites_count"] == 0
    assert favorite_only_after_clear_data["total_count"] == 0
    assert favorite_only_after_clear_data["publications"] == []

    favorite_state_result = await db_session.execute(
        text(
            """
            SELECT is_favorite
            FROM scholar_publications
            WHERE scholar_profile_id = :scholar_profile_id
              AND publication_id = :publication_id
            """
        ),
        {
            "scholar_profile_id": scholar_profile_id,
            "publication_id": publication_a_id,
        },
    )
    assert bool(favorite_state_result.scalar_one()) is False
