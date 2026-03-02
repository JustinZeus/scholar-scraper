from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.runtime_deps import get_scholar_source
from app.main import app
from app.services.scholar.rate_limit import reset_scholar_rate_limit_state_for_tests
from app.services.scholar.source import FetchResult
from app.settings import settings
from tests.integration.helpers import (
    api_csrf_headers,
    insert_user,
    login_user,
)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_scholars_crud_flow(db_session: AsyncSession) -> None:
    await insert_user(
        db_session,
        email="api-scholars@example.com",
        password="api-password",
    )

    client = TestClient(app)
    login_user(client, email="api-scholars@example.com", password="api-password")
    headers = api_csrf_headers(client)

    missing_csrf = client.post(
        "/api/v1/scholars",
        json={"scholar_id": "abcDEF123456"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_invalid"

    create_response = client.post(
        "/api/v1/scholars",
        json={"scholar_id": "abcDEF123456"},
        headers=headers,
    )
    assert create_response.status_code == 201
    created = create_response.json()["data"]
    assert created["scholar_id"] == "abcDEF123456"
    scholar_profile_id = int(created["id"])

    list_response = client.get("/api/v1/scholars")
    assert list_response.status_code == 200
    scholars = list_response.json()["data"]["scholars"]
    assert any(int(item["id"]) == scholar_profile_id for item in scholars)

    toggle_response = client.patch(
        f"/api/v1/scholars/{scholar_profile_id}/toggle",
        headers=headers,
    )
    assert toggle_response.status_code == 200
    assert toggle_response.json()["data"]["is_enabled"] is False

    delete_response = client.delete(
        f"/api/v1/scholars/{scholar_profile_id}",
        headers=headers,
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["message"] == "Scholar deleted."


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_scholars_search_and_profile_image_management(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    await insert_user(
        db_session,
        email="api-scholar-images@example.com",
        password="api-password",
    )

    class StubScholarSource:
        async def fetch_profile_html(self, scholar_id: str) -> FetchResult:
            assert scholar_id == "abcDEF123456"
            return FetchResult(
                requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                status_code=200,
                final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                body=(
                    "<html><head>"
                    '<meta property="og:image" content="https://images.example.com/ada.png" />'
                    "</head><body>"
                    '<div id="gsc_prf_in">Ada Lovelace</div>'
                    "</body></html>"
                ),
                error=None,
            )

        async def fetch_author_search_html(self, query: str, *, start: int) -> FetchResult:
            assert query == "Ada Lovelace"
            assert start == 0
            return FetchResult(
                requested_url="https://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=ada",
                status_code=200,
                final_url="https://scholar.google.com/citations?hl=en&view_op=search_authors&mauthors=ada",
                body=(
                    '<div class="gsc_1usr">'
                    '<img src="/citations/images/avatar_scholar_256.png" />'
                    '<a class="gs_ai_name" href="/citations?hl=en&user=abcDEF123456">Ada Lovelace</a>'
                    '<div class="gs_ai_aff">Analytical Engine</div>'
                    '<div class="gs_ai_eml">Verified email at computing.example</div>'
                    '<div class="gs_ai_cby">Cited by 42</div>'
                    '<a class="gs_ai_one_int">Mathematics</a>'
                    "</div>"
                ),
                error=None,
            )

    previous_upload_dir = settings.scholar_image_upload_dir
    previous_upload_max_bytes = settings.scholar_image_upload_max_bytes
    previous_queue_enabled = settings.ingestion_continuation_queue_enabled
    app.dependency_overrides[get_scholar_source] = lambda: StubScholarSource()
    object.__setattr__(settings, "scholar_image_upload_dir", str(tmp_path / "scholar_images"))
    object.__setattr__(settings, "scholar_image_upload_max_bytes", 1_000_000)
    object.__setattr__(settings, "ingestion_continuation_queue_enabled", False)

    try:
        client = TestClient(app)
        login_user(client, email="api-scholar-images@example.com", password="api-password")
        headers = api_csrf_headers(client)

        search_response = client.get("/api/v1/scholars/search", params={"query": "Ada Lovelace", "limit": 5})
        assert search_response.status_code == 200
        search_payload = search_response.json()["data"]
        assert search_payload["state"] == "ok"
        assert len(search_payload["candidates"]) == 1
        candidate = search_payload["candidates"][0]
        assert candidate["scholar_id"] == "abcDEF123456"
        assert candidate["profile_image_url"] == "https://scholar.google.com/citations/images/avatar_scholar_256.png"

        reset_scholar_rate_limit_state_for_tests()
        create_response = client.post(
            "/api/v1/scholars",
            json={
                "scholar_id": candidate["scholar_id"],
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        created = create_response.json()["data"]
        scholar_profile_id = int(created["id"])
        assert created["profile_image_source"] == "scraped"
        assert created["profile_image_url"] == "https://images.example.com/ada.png"

        set_url_response = client.put(
            f"/api/v1/scholars/{scholar_profile_id}/image/url",
            json={"image_url": "https://cdn.example.com/custom-avatar.png"},
            headers=headers,
        )
        assert set_url_response.status_code == 200
        set_url_data = set_url_response.json()["data"]
        assert set_url_data["profile_image_source"] == "override"
        assert set_url_data["profile_image_url"] == "https://cdn.example.com/custom-avatar.png"

        uploaded_bytes = b"\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01"
        upload_response = client.post(
            f"/api/v1/scholars/{scholar_profile_id}/image/upload",
            files={"image": ("avatar.png", uploaded_bytes, "image/png")},
            headers=headers,
        )
        assert upload_response.status_code == 200
        upload_data = upload_response.json()["data"]
        assert upload_data["profile_image_source"] == "upload"
        assert upload_data["profile_image_url"] == f"/scholar-images/{scholar_profile_id}/upload"

        uploaded_image_response = client.get(f"/scholar-images/{scholar_profile_id}/upload")
        assert uploaded_image_response.status_code == 200
        assert uploaded_image_response.headers["content-type"].startswith("image/png")
        assert uploaded_image_response.content == uploaded_bytes

        clear_response = client.delete(
            f"/api/v1/scholars/{scholar_profile_id}/image",
            headers=headers,
        )
        assert clear_response.status_code == 200
        clear_data = clear_response.json()["data"]
        assert clear_data["profile_image_source"] == "scraped"
        assert clear_data["profile_image_url"] == "https://images.example.com/ada.png"
    finally:
        app.dependency_overrides.pop(get_scholar_source, None)
        object.__setattr__(settings, "scholar_image_upload_dir", previous_upload_dir)
        object.__setattr__(
            settings,
            "scholar_image_upload_max_bytes",
            previous_upload_max_bytes,
        )
        object.__setattr__(settings, "ingestion_continuation_queue_enabled", previous_queue_enabled)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_scholar_import_export_round_trip(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-import-export@example.com",
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
            "display_name": "Existing Scholar",
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())
    publication_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 1)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 500):064x}",
            "title_raw": "Existing Publication",
            "title_normalized": "existingpublication",
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

    client = TestClient(app)
    login_user(client, email="api-import-export@example.com", password="api-password")
    headers = api_csrf_headers(client)

    export_response = client.get("/api/v1/scholars/export")
    assert export_response.status_code == 200
    export_payload = export_response.json()["data"]
    assert export_payload["schema_version"] == 1
    assert len(export_payload["scholars"]) == 1
    assert len(export_payload["publications"]) == 1

    import_response = client.post(
        "/api/v1/scholars/import",
        json={
            "schema_version": 1,
            "scholars": [
                {
                    "scholar_id": "abcDEF123456",
                    "display_name": "Updated Scholar",
                    "is_enabled": False,
                    "profile_image_override_url": "https://cdn.example.com/avatar.png",
                },
                {
                    "scholar_id": "zzzYYY111222",
                    "display_name": "Imported Scholar",
                    "is_enabled": True,
                    "profile_image_override_url": None,
                },
            ],
            "publications": [
                {
                    "scholar_id": "abcDEF123456",
                    "title": "Existing Publication",
                    "year": 2024,
                    "citation_count": 8,
                    "author_text": "A. Author",
                    "venue_text": "Test Venue",
                    "pub_url": "https://example.org/existing",
                    "pdf_url": "https://example.org/existing.pdf",
                    "is_read": True,
                },
                {
                    "scholar_id": "zzzYYY111222",
                    "title": "Imported Publication",
                    "year": 2025,
                    "citation_count": 2,
                    "author_text": "B. Author",
                    "venue_text": "Another Venue",
                    "pub_url": "https://example.org/imported",
                    "pdf_url": "https://example.org/imported.pdf",
                    "is_read": False,
                },
            ],
        },
        headers=headers,
    )
    assert import_response.status_code == 200
    import_data = import_response.json()["data"]
    assert int(import_data["scholars_created"]) == 1
    assert int(import_data["scholars_updated"]) >= 1
    assert int(import_data["publications_created"]) == 1
    assert int(import_data["links_created"]) == 1

    updated_scholar_result = await db_session.execute(
        text(
            """
            SELECT display_name, is_enabled, profile_image_override_url
            FROM scholar_profiles
            WHERE user_id = :user_id AND scholar_id = :scholar_id
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
        },
    )
    updated_scholar = updated_scholar_result.one()
    assert updated_scholar[0] == "Updated Scholar"
    assert updated_scholar[1] is False
    assert updated_scholar[2] == "https://cdn.example.com/avatar.png"

    imported_pub_result = await db_session.execute(
        text(
            """
            SELECT p.title_raw, p.pdf_url
            FROM publications p
            WHERE p.title_raw = :title
            """
        ),
        {"title": "Imported Publication"},
    )
    imported_pub = imported_pub_result.one()
    assert imported_pub[0] == "Imported Publication"
    assert imported_pub[1] == "https://example.org/imported.pdf"

    updated_link_result = await db_session.execute(
        text(
            """
            SELECT sp.is_read
            FROM scholar_publications sp
            JOIN scholar_profiles s ON s.id = sp.scholar_profile_id
            JOIN publications p ON p.id = sp.publication_id
            WHERE s.user_id = :user_id
              AND s.scholar_id = :scholar_id
              AND p.title_raw = :title
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
            "title": "Existing Publication",
        },
    )
    assert bool(updated_link_result.scalar_one()) is True
