from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.runtime_deps import get_ingestion_service
from app.db.models import CrawlRun, Publication, RunStatus, RunTriggerType
from app.main import app
from app.services.ingestion.application import ScholarIngestionService
from app.services.ingestion.run_enrichment import background_enrich
from app.services.scholar.source import FetchResult
from tests.integration.helpers import insert_user, login_user


class _PassthroughSource:
    """Minimal source that passes preflight without making real requests."""

    async def fetch_profile_html(self, scholar_id: str) -> FetchResult:
        return FetchResult(
            requested_url=f"https://scholar.google.com/citations?user={scholar_id}",
            status_code=200,
            final_url=f"https://scholar.google.com/citations?user={scholar_id}",
            body="<html></html>",
            error=None,
        )

    async def fetch_profile_page_html(
        self, scholar_id: str, *, cstart: int, pagesize: int
    ) -> FetchResult:
        return await self.fetch_profile_html(scholar_id)


def _csrf_headers(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    csrf_token = response.json()["data"]["csrf_token"]
    assert isinstance(csrf_token, str) and csrf_token
    return {"X-CSRF-Token": csrf_token}


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_crawl_runs_enforce_single_active_run_per_user(db_session: AsyncSession) -> None:
    user_id = await insert_user(
        db_session,
        email="api-single-active@example.com",
        password="api-password",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO crawl_runs (user_id, trigger_type, status, scholar_count, new_pub_count)
            VALUES (:user_id, 'manual', 'running', 1, 0)
            """
        ),
        {"user_id": user_id},
    )
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                """
                INSERT INTO crawl_runs (user_id, trigger_type, status, scholar_count, new_pub_count)
                VALUES (:user_id, 'scheduled', 'resolving', 1, 0)
                """
            ),
            {"user_id": user_id},
        )
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_manual_run_conflicts_when_an_active_run_exists(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-run-conflict@example.com",
        password="api-password",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, true)
            """
        ),
        {"user_id": user_id, "scholar_id": "runConflict001", "display_name": "Run Conflict"},
    )
    await db_session.commit()

    service = ScholarIngestionService(source=_PassthroughSource())

    async def _stall_execute_run(**_kwargs: Any) -> None:
        await asyncio.sleep(0.4)

    monkeypatch.setattr(service, "execute_run", _stall_execute_run)
    app.dependency_overrides[get_ingestion_service] = lambda: service
    try:
        client = TestClient(app)
        login_user(client, email="api-run-conflict@example.com", password="api-password")
        headers = _csrf_headers(client)

        first_response = client.post("/api/v1/runs/manual", headers=headers)
        assert first_response.status_code == 200
        assert first_response.json()["data"]["status"] == "running"

        second_response = client.post("/api/v1/runs/manual", headers=headers)
        assert second_response.status_code == 409
        payload = second_response.json()
        assert payload["error"]["code"] == "run_in_progress"
        await asyncio.sleep(0.45)
    finally:
        app.dependency_overrides.pop(get_ingestion_service, None)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_api_cancel_allows_resolving_and_rejects_terminal_run(db_session: AsyncSession) -> None:
    user_id = await insert_user(
        db_session,
        email="api-cancel-resolving@example.com",
        password="api-password",
    )
    run_result = await db_session.execute(
        text(
            """
            INSERT INTO crawl_runs (user_id, trigger_type, status, scholar_count, new_pub_count)
            VALUES (:user_id, 'manual', 'resolving', 1, 2)
            RETURNING id
            """
        ),
        {"user_id": user_id},
    )
    run_id = int(run_result.scalar_one())
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="api-cancel-resolving@example.com", password="api-password")
    headers = _csrf_headers(client)

    cancel_response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=headers)
    assert cancel_response.status_code == 200
    assert cancel_response.json()["data"]["run"]["status"] == "canceled"

    cancel_again_response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=headers)
    assert cancel_again_response.status_code == 409
    assert cancel_again_response.json()["error"]["code"] == "run_not_cancelable"


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_background_enrichment_preserves_canceled_status(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-cancel-enrichment@example.com",
        password="api-password",
    )
    scholar_result = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, 'cancelResolve001', 'Cancel Resolve', true)
            RETURNING id
            """
        ),
        {"user_id": user_id},
    )
    scholar_profile_id = int(scholar_result.scalar_one())
    run = CrawlRun(
        user_id=user_id,
        trigger_type=RunTriggerType.MANUAL,
        status=RunStatus.RESOLVING,
        scholar_count=1,
    )
    publication = Publication(
        fingerprint_sha256=f"{(user_id + 9000):064x}",
        title_raw="Cancel During Resolving",
        title_normalized="cancel during resolving",
        citation_count=0,
        openalex_enriched=False,
    )
    db_session.add_all([run, publication])
    await db_session.flush()
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (
                scholar_profile_id,
                publication_id,
                first_seen_run_id,
                is_read
            )
            VALUES (:scholar_profile_id, :publication_id, :run_id, false)
            """
        ),
        {
            "scholar_profile_id": scholar_profile_id,
            "publication_id": int(publication.id),
            "run_id": int(run.id),
        },
    )
    await db_session.commit()

    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    class _OpenAlexClientStub:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = (args, kwargs)

        async def get_works_by_filter(self, *_args: Any, **_kwargs: Any) -> list[Any]:
            async with session_factory() as cancel_session:
                run_to_cancel = await cancel_session.get(CrawlRun, int(run.id))
                assert run_to_cancel is not None
                run_to_cancel.status = RunStatus.CANCELED
                await cancel_session.commit()
            return []

    monkeypatch.setattr(
        "app.services.openalex.client.OpenAlexClient",
        _OpenAlexClientStub,
    )

    from app.services.ingestion.enrichment import EnrichmentRunner

    enrichment_runner = EnrichmentRunner()
    await background_enrich(
        session_factory,
        enrichment_runner,
        run_id=int(run.id),
        intended_final_status=RunStatus.SUCCESS,
    )

    await db_session.refresh(run)
    await db_session.refresh(publication)
    assert run.status == RunStatus.CANCELED
    assert publication.openalex_enriched is False


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_publications_list_endpoint_does_not_raise_name_error(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-publications-nameerror@example.com",
        password="api-password",
    )
    scholar_result = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, 'pubNameError001', 'Pub NameError', true)
            RETURNING id
            """
        ),
        {"user_id": user_id},
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
            "fingerprint": f"{(user_id + 2222):064x}",
            "title_raw": "NameError Regression",
            "title_normalized": "nameerror regression",
        },
    )
    publication_id = int(publication_result.scalar_one())
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
    login_user(client, email="api-publications-nameerror@example.com", password="api-password")
    response = client.get("/api/v1/publications?mode=all&limit=10&offset=0")
    assert response.status_code == 200
    assert len(response.json()["data"]["publications"]) == 1


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_partial_discovery_exception_keeps_new_pub_count_consistent(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-pub-count-consistency@example.com",
        password="api-password",
    )
    scholar_result = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, 'countConsistency001', 'Count Consistency', true)
            RETURNING id
            """
        ),
        {"user_id": user_id},
    )
    scholar_profile_id = int(scholar_result.scalar_one())

    run = CrawlRun(
        user_id=user_id,
        trigger_type=RunTriggerType.MANUAL,
        status=RunStatus.RUNNING,
        scholar_count=1,
        new_pub_count=0,
    )
    publication = Publication(
        fingerprint_sha256=f"{(user_id + 777):064x}",
        title_raw="Persisted Discovery",
        title_normalized="persisted discovery",
        citation_count=0,
    )
    db_session.add_all([run, publication])
    await db_session.commit()

    call_count = 0

    async def _resolve_publication_stub(*_args: Any, **_kwargs: Any) -> Publication:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return publication
        raise RuntimeError("mid_page_failure")

    from app.services.ingestion import publication_upsert

    monkeypatch.setattr(publication_upsert, "resolve_publication", _resolve_publication_stub)

    from app.db.models import ScholarProfile
    from app.services.scholar.parser_types import PublicationCandidate

    scholar = await db_session.get(ScholarProfile, scholar_profile_id)
    assert scholar is not None

    publications = [
        PublicationCandidate(
            title="Persisted Discovery",
            title_url=None,
            cluster_id=None,
            year=None,
            citation_count=0,
            authors_text=None,
            venue_text=None,
            pdf_url=None,
        ),
        PublicationCandidate(
            title="Will Fail",
            title_url=None,
            cluster_id=None,
            year=None,
            citation_count=0,
            authors_text=None,
            venue_text=None,
            pdf_url=None,
        ),
    ]

    with pytest.raises(RuntimeError, match="mid_page_failure"):
        await publication_upsert.upsert_profile_publications(
            db_session,
            run=run,
            scholar=scholar,
            publications=publications,
        )

    refreshed_run = await db_session.get(CrawlRun, int(run.id))
    assert refreshed_run is not None
    assert int(refreshed_run.new_pub_count) == 1
    link_count_result = await db_session.execute(
        text(
            """
            SELECT count(*)
            FROM scholar_publications
            WHERE scholar_profile_id = :scholar_profile_id
              AND first_seen_run_id = :run_id
            """
        ),
        {"scholar_profile_id": scholar_profile_id, "run_id": int(run.id)},
    )
    assert int(link_count_result.scalar_one()) == 1


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_publications_pagination_snapshot_stays_stable_across_inserts(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="api-publications-snapshot@example.com",
        password="api-password",
    )
    scholar_result = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, 'pagingSnapshot001', 'Paging Snapshot', true)
            RETURNING id
            """
        ),
        {"user_id": user_id},
    )
    scholar_profile_id = int(scholar_result.scalar_one())

    publication_ids: list[int] = []
    for index in range(4):
        created = await db_session.execute(
            text(
                """
                INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
                VALUES (:fingerprint, :title_raw, :title_normalized, 1)
                RETURNING id
                """
            ),
            {
                "fingerprint": f"{(user_id + 1000 + index):064x}",
                "title_raw": f"Stable Page {index}",
                "title_normalized": f"stable page {index}",
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
    login_user(client, email="api-publications-snapshot@example.com", password="api-password")

    first_page_response = client.get("/api/v1/publications?mode=all&page=1&page_size=2")
    assert first_page_response.status_code == 200
    first_page = first_page_response.json()["data"]
    first_page_ids = [int(item["publication_id"]) for item in first_page["publications"]]
    snapshot = first_page["snapshot"]
    assert isinstance(snapshot, str) and snapshot

    inserted = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, citation_count)
            VALUES (:fingerprint, :title_raw, :title_normalized, 1)
            RETURNING id
            """
        ),
        {
            "fingerprint": f"{(user_id + 5000):064x}",
            "title_raw": "Inserted After Snapshot",
            "title_normalized": "inserted after snapshot",
        },
    )
    inserted_publication_id = int(inserted.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read, is_favorite)
            VALUES (:scholar_profile_id, :publication_id, false, false)
            """
        ),
        {"scholar_profile_id": scholar_profile_id, "publication_id": inserted_publication_id},
    )
    await db_session.commit()

    second_page_response = client.get(
        "/api/v1/publications",
        params={
            "mode": "all",
            "page": 2,
            "page_size": 2,
            "snapshot": snapshot,
        },
    )
    assert second_page_response.status_code == 200
    second_page = second_page_response.json()["data"]
    second_page_ids = [int(item["publication_id"]) for item in second_page["publications"]]

    first_page_again_response = client.get(
        "/api/v1/publications",
        params={
            "mode": "all",
            "page": 1,
            "page_size": 2,
            "snapshot": snapshot,
        },
    )
    assert first_page_again_response.status_code == 200
    first_page_again = first_page_again_response.json()["data"]
    first_page_again_ids = [int(item["publication_id"]) for item in first_page_again["publications"]]

    assert first_page_again_ids == first_page_ids
    assert not (set(first_page_ids) & set(second_page_ids))
    assert inserted_publication_id not in set(first_page_ids + second_page_ids)
