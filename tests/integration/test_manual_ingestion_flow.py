from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app, get_scholar_source
from app.db.models import RunTriggerType
from app.services.ingestion import RUN_LOCK_NAMESPACE, RunAlreadyInProgressError, ScholarIngestionService
from app.services.scheduler import SchedulerService
from app.services.scholar_source import FetchResult
from tests.integration.helpers import extract_csrf_token, insert_user, login_user

HTML_BASELINE = """
<html>
  <div id="gsc_prf_in">Fixture Scholar</div>
  <span id="gsc_a_nn">Articles 1-1</span>
  <table><tbody id="gsc_a_b">
    <tr class="gsc_a_tr">
      <td class="gsc_a_t">
        <a class="gsc_a_at" href="/citations?view_op=view_citation&hl=en&citation_for_view=abcDEF123456:cluster1">Paper One</a>
        <div class="gs_gray">A Author</div>
        <div class="gs_gray">Venue One, 2024</div>
      </td>
      <td class="gsc_a_c"><a class="gsc_a_ac">3</a></td>
      <td class="gsc_a_y"><span class="gsc_a_h">2024</span></td>
    </tr>
  </tbody></table>
</html>
"""

HTML_INCREMENTAL = """
<html>
  <div id="gsc_prf_in">Fixture Scholar</div>
  <span id="gsc_a_nn">Articles 1-2</span>
  <table><tbody id="gsc_a_b">
    <tr class="gsc_a_tr">
      <td class="gsc_a_t">
        <a class="gsc_a_at" href="/citations?view_op=view_citation&hl=en&citation_for_view=abcDEF123456:cluster1">Paper One</a>
        <div class="gs_gray">A Author</div>
        <div class="gs_gray">Venue One, 2024</div>
      </td>
      <td class="gsc_a_c"><a class="gsc_a_ac">4</a></td>
      <td class="gsc_a_y"><span class="gsc_a_h">2024</span></td>
    </tr>
    <tr class="gsc_a_tr">
      <td class="gsc_a_t">
        <a class="gsc_a_at" href="/citations?view_op=view_citation&hl=en&citation_for_view=abcDEF123456:cluster2">Paper Two</a>
        <div class="gs_gray">B Author</div>
        <div class="gs_gray">Venue Two, 2025</div>
      </td>
      <td class="gsc_a_c"><a class="gsc_a_ac">1</a></td>
      <td class="gsc_a_y"><span class="gsc_a_h">2025</span></td>
    </tr>
  </tbody></table>
</html>
"""

HTML_PAGED_ONE = """
<html>
  <div id="gsc_prf_in">Paged Scholar</div>
  <span id="gsc_a_nn">Articles 1-1</span>
  <table><tbody id="gsc_a_b">
    <tr class="gsc_a_tr">
      <td class="gsc_a_t">
        <a class="gsc_a_at" href="/citations?view_op=view_citation&hl=en&citation_for_view=abcDEF123456:paged1">Paged Paper One</a>
        <div class="gs_gray">P Author</div>
        <div class="gs_gray">Paged Venue, 2023</div>
      </td>
      <td class="gsc_a_c"><a class="gsc_a_ac">5</a></td>
      <td class="gsc_a_y"><span class="gsc_a_h">2023</span></td>
    </tr>
  </tbody></table>
  <div id="gsc_lwp">
    <button id="gsc_bpf_more" type="button">Show more</button>
  </div>
</html>
"""

HTML_PAGED_TWO = """
<html>
  <div id="gsc_prf_in">Paged Scholar</div>
  <span id="gsc_a_nn">Articles 2-2</span>
  <table><tbody id="gsc_a_b">
    <tr class="gsc_a_tr">
      <td class="gsc_a_t">
        <a class="gsc_a_at" href="/citations?view_op=view_citation&hl=en&citation_for_view=abcDEF123456:paged2">Paged Paper Two</a>
        <div class="gs_gray">P Author</div>
        <div class="gs_gray">Paged Venue, 2024</div>
      </td>
      <td class="gsc_a_c"><a class="gsc_a_ac">2</a></td>
      <td class="gsc_a_y"><span class="gsc_a_h">2024</span></td>
    </tr>
  </tbody></table>
</html>
"""

HTML_STALLED_TAIL_ONE = """
<html>
  <div id="gsc_prf_in">Tail Scholar</div>
  <span id="gsc_a_nn">Articles 1-1</span>
  <table><tbody id="gsc_a_b">
    <tr class="gsc_a_tr">
      <td class="gsc_a_t">
        <a class="gsc_a_at" href="/citations?view_op=view_citation&hl=en&citation_for_view=abcDEF123456:tail1">Tail Paper One</a>
        <div class="gs_gray">T Author</div>
        <div class="gs_gray">Tail Venue, 2022</div>
      </td>
      <td class="gsc_a_c"><a class="gsc_a_ac">9</a></td>
      <td class="gsc_a_y"><span class="gsc_a_h">2022</span></td>
    </tr>
  </tbody></table>
  <div id="gsc_lwp"><button id="gsc_bpf_more" type="button">Show more</button></div>
</html>
"""

HTML_STALLED_TAIL_TWO = """
<html>
  <div id="gsc_prf_in">Tail Scholar</div>
  <div>No documents. Your search didn't match any articles.</div>
  <div id="gsc_lwp"><button id="gsc_bpf_more" type="button">Show more</button></div>
</html>
"""


class StubScholarSource:
    def __init__(self, html_bodies: list[str]) -> None:
        self._html_bodies = html_bodies
        self._index = 0

    async def fetch_profile_html(self, scholar_id: str) -> FetchResult:
        if self._index >= len(self._html_bodies):
            body = self._html_bodies[-1]
        else:
            body = self._html_bodies[self._index]
        self._index += 1

        url = f"https://scholar.google.com/citations?hl=en&user={scholar_id}"
        return FetchResult(
            requested_url=url,
            status_code=200,
            final_url=url,
            body=body,
            error=None,
        )


class StubScholarSourceResults:
    def __init__(self, results: list[FetchResult]) -> None:
        self._results = results
        self._index = 0

    async def fetch_profile_html(self, scholar_id: str) -> FetchResult:
        if self._index >= len(self._results):
            result = self._results[-1]
        else:
            result = self._results[self._index]
        self._index += 1
        return result


class CountingScholarSourceResults(StubScholarSourceResults):
    def __init__(self, results: list[FetchResult]) -> None:
        super().__init__(results)
        self.calls = 0

    async def fetch_profile_html(self, scholar_id: str) -> FetchResult:
        self.calls += 1
        return await super().fetch_profile_html(scholar_id)


class StubPagedScholarSource:
    def __init__(self, pages: dict[int, str]) -> None:
        self._pages = pages
        self.calls: list[tuple[int, int]] = []

    async def fetch_profile_html(self, scholar_id: str) -> FetchResult:
        return await self.fetch_profile_page_html(
            scholar_id,
            cstart=0,
            pagesize=100,
        )

    async def fetch_profile_page_html(
        self,
        scholar_id: str,
        *,
        cstart: int,
        pagesize: int,
    ) -> FetchResult:
        self.calls.append((cstart, pagesize))
        body = self._pages.get(cstart, "<html><body></body></html>")
        url = (
            "https://scholar.google.com/citations"
            f"?hl=en&user={scholar_id}&cstart={cstart}&pagesize={pagesize}"
        )
        return FetchResult(
            requested_url=url,
            status_code=200,
            final_url=url,
            body=body,
            error=None,
        )


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_manual_ingestion_sets_baseline_then_adds_unread(db_session: AsyncSession) -> None:
    user_id = await insert_user(
        db_session,
        email="ingest@example.com",
        password="ingest-password",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, :is_enabled)
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
            "display_name": "Fixture Scholar",
            "is_enabled": True,
        },
    )
    await db_session.commit()

    stub_source = StubScholarSource([HTML_BASELINE, HTML_INCREMENTAL])
    app.dependency_overrides[get_scholar_source] = lambda: stub_source

    client = TestClient(app)
    try:
        login_user(client, email="ingest@example.com", password="ingest-password")

        dashboard = client.get("/")
        csrf = extract_csrf_token(dashboard.text)
        run_one = client.post(
            "/runs/manual",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert run_one.status_code == 303
        assert run_one.headers["location"].startswith("/")

        baseline_status = await db_session.execute(
            text("SELECT baseline_completed FROM scholar_profiles WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        assert baseline_status.scalar_one() is True

        run_one_stats = await db_session.execute(
            text(
                """
                SELECT status::text, new_pub_count
                FROM crawl_runs
                WHERE user_id = :user_id
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        )
        assert run_one_stats.one() == ("success", 1)

        unread_after_baseline = await db_session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM scholar_publications sp
                JOIN scholar_profiles s ON s.id = sp.scholar_profile_id
                WHERE s.user_id = :user_id AND sp.is_read = false
                """
            ),
            {"user_id": user_id},
        )
        assert unread_after_baseline.scalar_one() == 1

        dashboard_again = client.get("/")
        csrf_two = extract_csrf_token(dashboard_again.text)
        run_two = client.post(
            "/runs/manual",
            data={"csrf_token": csrf_two},
            follow_redirects=False,
        )
        assert run_two.status_code == 303

        run_two_stats = await db_session.execute(
            text(
                """
                SELECT status::text, new_pub_count
                FROM crawl_runs
                WHERE user_id = :user_id
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        )
        assert run_two_stats.one() == ("success", 1)

        unread_after_second = await db_session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM scholar_publications sp
                JOIN scholar_profiles s ON s.id = sp.scholar_profile_id
                WHERE s.user_id = :user_id AND sp.is_read = false
                """
            ),
            {"user_id": user_id},
        )
        assert unread_after_second.scalar_one() == 2

        publications_new_page = client.get("/publications?mode=new")
        assert publications_new_page.status_code == 200
        assert "Paper Two" in publications_new_page.text
        assert "Paper One" not in publications_new_page.text

        publications_all_page = client.get("/publications?mode=all")
        assert publications_all_page.status_code == 200
        assert "Paper One" in publications_all_page.text
        assert "Paper Two" in publications_all_page.text

        dashboard_mark = client.get("/")
        csrf_mark = extract_csrf_token(dashboard_mark.text)
        mark_response = client.post(
            "/publications/mark-all-read",
            data={"csrf_token": csrf_mark},
            follow_redirects=False,
        )
        assert mark_response.status_code == 303

        unread_after_mark = await db_session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM scholar_publications sp
                JOIN scholar_profiles s ON s.id = sp.scholar_profile_id
                WHERE s.user_id = :user_id AND sp.is_read = false
                """
            ),
            {"user_id": user_id},
        )
        assert unread_after_mark.scalar_one() == 0

        publications_new_after_mark = client.get("/publications?mode=new")
        assert publications_new_after_mark.status_code == 200
        assert "Paper Two" in publications_new_after_mark.text
        assert "Paper One" not in publications_new_after_mark.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_publications_page_supports_scholar_filtering_navigation(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="filtering@example.com",
        password="filter-password",
    )

    scholar_one_result = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, :is_enabled)
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
            "display_name": "Scholar One",
            "is_enabled": True,
        },
    )
    scholar_one_id = int(scholar_one_result.scalar_one())

    scholar_two_result = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, :is_enabled)
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "uvwXYZ987654",
            "display_name": "Scholar Two",
            "is_enabled": True,
        },
    )
    scholar_two_id = int(scholar_two_result.scalar_one())

    run_result = await db_session.execute(
        text(
            """
            INSERT INTO crawl_runs (
                user_id,
                trigger_type,
                status,
                start_dt,
                end_dt,
                scholar_count,
                new_pub_count,
                error_log
            )
            VALUES (
                :user_id,
                'manual',
                'success',
                NOW(),
                NOW(),
                2,
                2,
                '{}'::jsonb
            )
            RETURNING id
            """
        ),
        {"user_id": user_id},
    )
    run_id = int(run_result.scalar_one())

    publication_one_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (
                cluster_id,
                fingerprint_sha256,
                title_raw,
                title_normalized,
                year,
                citation_count,
                author_text,
                venue_text,
                pub_url,
                pdf_url
            )
            VALUES (
                NULL,
                :fingerprint,
                :title_raw,
                :title_normalized,
                :year,
                0,
                NULL,
                NULL,
                NULL,
                NULL
            )
            RETURNING id
            """
        ),
        {
            "fingerprint": "f" * 64,
            "title_raw": "Scholar One Paper",
            "title_normalized": "scholar one paper",
            "year": 2024,
        },
    )
    publication_one_id = int(publication_one_result.scalar_one())

    publication_two_result = await db_session.execute(
        text(
            """
            INSERT INTO publications (
                cluster_id,
                fingerprint_sha256,
                title_raw,
                title_normalized,
                year,
                citation_count,
                author_text,
                venue_text,
                pub_url,
                pdf_url
            )
            VALUES (
                NULL,
                :fingerprint,
                :title_raw,
                :title_normalized,
                :year,
                0,
                NULL,
                NULL,
                NULL,
                NULL
            )
            RETURNING id
            """
        ),
        {
            "fingerprint": "e" * 64,
            "title_raw": "Scholar Two Paper",
            "title_normalized": "scholar two paper",
            "year": 2025,
        },
    )
    publication_two_id = int(publication_two_result.scalar_one())

    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read, first_seen_run_id)
            VALUES (:scholar_profile_id, :publication_id, :is_read, :first_seen_run_id)
            """
        ),
        {
            "scholar_profile_id": scholar_one_id,
            "publication_id": publication_one_id,
            "is_read": False,
            "first_seen_run_id": run_id,
        },
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read, first_seen_run_id)
            VALUES (:scholar_profile_id, :publication_id, :is_read, :first_seen_run_id)
            """
        ),
        {
            "scholar_profile_id": scholar_two_id,
            "publication_id": publication_two_id,
            "is_read": False,
            "first_seen_run_id": run_id,
        },
    )
    await db_session.commit()

    client = TestClient(app)
    login_user(client, email="filtering@example.com", password="filter-password")

    scholars_page = client.get("/scholars")
    assert scholars_page.status_code == 200
    assert f"/publications?mode=new&scholar_profile_id={scholar_one_id}" in scholars_page.text
    assert f"/publications?mode=all&scholar_profile_id={scholar_two_id}" in scholars_page.text

    filtered_all = client.get(f"/publications?mode=all&scholar_profile_id={scholar_one_id}")
    assert filtered_all.status_code == 200
    assert "Scholar One Paper" in filtered_all.text
    assert "Scholar Two Paper" not in filtered_all.text

    filtered_new = client.get(f"/publications?mode=new&scholar_profile_id={scholar_two_id}")
    assert filtered_new.status_code == 200
    assert "Scholar Two Paper" in filtered_new.text
    assert "Scholar One Paper" not in filtered_new.text


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_manual_ingestion_persists_failure_debug_context(db_session: AsyncSession) -> None:
    user_id = await insert_user(
        db_session,
        email="ingest-failure@example.com",
        password="ingest-password",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, :is_enabled)
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
            "display_name": "Failure Fixture",
            "is_enabled": True,
        },
    )
    await db_session.commit()

    stub_source = StubScholarSourceResults(
        [
            FetchResult(
                requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                status_code=None,
                final_url=None,
                body="",
                error="timed out",
            )
        ]
    )
    app.dependency_overrides[get_scholar_source] = lambda: stub_source

    client = TestClient(app)
    try:
        login_user(client, email="ingest-failure@example.com", password="ingest-password")
        dashboard = client.get("/")
        csrf = extract_csrf_token(dashboard.text)
        run_response = client.post(
            "/runs/manual",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert run_response.status_code == 303

        run_result = await db_session.execute(
            text(
                """
                SELECT status::text, error_log
                FROM crawl_runs
                WHERE user_id = :user_id
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        )
        status_text, error_log = run_result.one()
        assert status_text == "failed"
        assert error_log["summary"]["failed_count"] == 1
        assert error_log["summary"]["failed_state_counts"] == {"network_error": 1}
        assert error_log["summary"]["failed_reason_counts"] == {
            "network_error_missing_status_code": 1
        }

        scholar_result = error_log["scholar_results"][0]
        assert scholar_result["state"] == "network_error"
        assert scholar_result["state_reason"] == "network_error_missing_status_code"
        debug = scholar_result["debug"]
        assert debug["status_code"] is None
        assert debug["fetch_error"] == "timed out"
        assert debug["requested_url"].endswith("user=abcDEF123456")
        assert debug["body_excerpt"] is None

        runs_page = client.get("/runs")
        assert runs_page.status_code == 200
        assert "Run History" in runs_page.text
        assert "failed /" in runs_page.text

        failed_only_page = client.get("/runs?failed_only=1")
        assert failed_only_page.status_code == 200
        assert "Run History" in failed_only_page.text

        run_id_result = await db_session.execute(
            text(
                """
                SELECT id
                FROM crawl_runs
                WHERE user_id = :user_id
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        )
        run_id = run_id_result.scalar_one()

        detail_page = client.get(f"/runs/{run_id}")
        assert detail_page.status_code == 200
        assert f"Run #{run_id}" in detail_page.text
        assert "network_error_missing_status_code" in detail_page.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_manual_ingestion_fetches_all_pages_for_scholar(db_session: AsyncSession) -> None:
    user_id = await insert_user(
        db_session,
        email="paged@example.com",
        password="ingest-password",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, :is_enabled)
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
            "display_name": "Paged Scholar",
            "is_enabled": True,
        },
    )
    await db_session.commit()

    source = StubPagedScholarSource(
        {
            0: HTML_PAGED_ONE,
            1: HTML_PAGED_TWO,
        }
    )
    app.dependency_overrides[get_scholar_source] = lambda: source

    client = TestClient(app)
    try:
        login_user(client, email="paged@example.com", password="ingest-password")
        dashboard = client.get("/")
        csrf = extract_csrf_token(dashboard.text)
        run_response = client.post(
            "/runs/manual",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert run_response.status_code == 303

        assert source.calls[0][0] == 0
        assert source.calls[1][0] == 1

        publications_count = await db_session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM scholar_publications sp
                JOIN scholar_profiles s ON s.id = sp.scholar_profile_id
                WHERE s.user_id = :user_id
                """
            ),
            {"user_id": user_id},
        )
        assert publications_count.scalar_one() == 2

        run_result = await db_session.execute(
            text(
                """
                SELECT status::text, new_pub_count, error_log
                FROM crawl_runs
                WHERE user_id = :user_id
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        )
        status_text, new_pub_count, error_log = run_result.one()
        assert status_text == "success"
        assert new_pub_count == 2
        scholar_result = error_log["scholar_results"][0]
        assert scholar_result["publication_count"] == 2
        assert scholar_result["pages_fetched"] == 2
        assert scholar_result["has_more_remaining"] is False
        assert scholar_result["pagination_truncated_reason"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_manual_ingestion_handles_empty_no_results_tail_without_partial(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="tail@example.com",
        password="ingest-password",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, :is_enabled)
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
            "display_name": "Tail Scholar",
            "is_enabled": True,
        },
    )
    await db_session.commit()

    source = StubPagedScholarSource(
        {
            0: HTML_STALLED_TAIL_ONE,
            1: HTML_STALLED_TAIL_TWO,
        }
    )
    app.dependency_overrides[get_scholar_source] = lambda: source

    client = TestClient(app)
    try:
        login_user(client, email="tail@example.com", password="ingest-password")
        dashboard = client.get("/")
        csrf = extract_csrf_token(dashboard.text)
        run_response = client.post(
            "/runs/manual",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert run_response.status_code == 303
        assert source.calls[0][0] == 0
        assert source.calls[1][0] == 1

        run_result = await db_session.execute(
            text(
                """
                SELECT status::text, new_pub_count, error_log
                FROM crawl_runs
                WHERE user_id = :user_id
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        )
        status_text, new_pub_count, error_log = run_result.one()
        assert status_text == "success"
        assert new_pub_count == 1
        scholar_result = error_log["scholar_results"][0]
        assert scholar_result["outcome"] == "success"
        assert scholar_result["pagination_truncated_reason"] is None

        queue_count_result = await db_session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM ingestion_queue_items
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id},
        )
        assert queue_count_result.scalar_one() == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_ingestion_enqueues_continuation_when_max_pages_reached(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="queued@example.com",
        password="ingest-password",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, :is_enabled)
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
            "display_name": "Queued Scholar",
            "is_enabled": True,
        },
    )
    await db_session.commit()

    source = StubPagedScholarSource({0: HTML_PAGED_ONE, 1: HTML_PAGED_TWO})
    service = ScholarIngestionService(source=source)

    summary = await service.run_for_user(
        db_session,
        user_id=user_id,
        trigger_type=RunTriggerType.MANUAL,
        request_delay_seconds=0,
        network_error_retries=0,
        retry_backoff_seconds=0,
        max_pages_per_scholar=1,
        page_size=100,
        auto_queue_continuations=True,
        queue_delay_seconds=0,
    )

    assert summary.status.value == "partial_failure"
    queue_result = await db_session.execute(
        text(
            """
            SELECT reason, resume_cstart, attempt_count
            FROM ingestion_queue_items
            WHERE user_id = :user_id
            """
        ),
        {"user_id": user_id},
    )
    reason, resume_cstart, attempt_count = queue_result.one()
    assert reason == "max_pages_reached"
    assert int(resume_cstart) == 1
    assert int(attempt_count) == 0


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_scheduler_processes_queued_continuation_items(
    db_session: AsyncSession,
) -> None:
    user_id = await insert_user(
        db_session,
        email="queue-scheduler@example.com",
        password="ingest-password",
    )
    scholar_result = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, :is_enabled)
            RETURNING id
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
            "display_name": "Queue Scheduler Scholar",
            "is_enabled": True,
        },
    )
    scholar_profile_id = int(scholar_result.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO ingestion_queue_items (
                user_id,
                scholar_profile_id,
                resume_cstart,
                reason,
                attempt_count,
                next_attempt_dt
            )
            VALUES (
                :user_id,
                :scholar_profile_id,
                :resume_cstart,
                :reason,
                :attempt_count,
                NOW() - INTERVAL '1 minute'
            )
            """
        ),
        {
            "user_id": user_id,
            "scholar_profile_id": scholar_profile_id,
            "resume_cstart": 1,
            "reason": "max_pages_reached",
            "attempt_count": 0,
        },
    )
    await db_session.commit()

    source = StubPagedScholarSource({1: HTML_PAGED_TWO})
    scheduler = SchedulerService(
        enabled=True,
        tick_seconds=60,
        network_error_retries=0,
        retry_backoff_seconds=0,
        max_pages_per_scholar=30,
        page_size=100,
        continuation_queue_enabled=True,
        continuation_base_delay_seconds=1,
        continuation_max_delay_seconds=60,
        continuation_max_attempts=4,
        queue_batch_size=10,
    )
    scheduler._source = source

    await scheduler._tick_once()

    queue_count_result = await db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM ingestion_queue_items
            WHERE user_id = :user_id
            """
        ),
        {"user_id": user_id},
    )
    assert queue_count_result.scalar_one() == 0

    publications_count = await db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM scholar_publications sp
            JOIN scholar_profiles s ON s.id = sp.scholar_profile_id
            WHERE s.user_id = :user_id
            """
        ),
        {"user_id": user_id},
    )
    assert publications_count.scalar_one() == 1
    assert source.calls and source.calls[0][0] == 1


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_ingestion_retries_network_error_and_recovers(db_session: AsyncSession) -> None:
    user_id = await insert_user(
        db_session,
        email="retry@example.com",
        password="ingest-password",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, :is_enabled)
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
            "display_name": "Retry Fixture",
            "is_enabled": True,
        },
    )
    await db_session.commit()

    source = CountingScholarSourceResults(
        [
            FetchResult(
                requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                status_code=None,
                final_url=None,
                body="",
                error="temporary timeout",
            ),
            FetchResult(
                requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                status_code=200,
                final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                body=HTML_BASELINE,
                error=None,
            ),
        ]
    )
    service = ScholarIngestionService(source=source)

    summary = await service.run_for_user(
        db_session,
        user_id=user_id,
        trigger_type=RunTriggerType.MANUAL,
        request_delay_seconds=0,
        network_error_retries=1,
        retry_backoff_seconds=0,
    )

    assert source.calls == 2
    assert summary.status.value == "success"
    assert summary.failed_count == 0
    assert summary.succeeded_count == 1

    run_error_log_result = await db_session.execute(
        text(
            """
            SELECT error_log
            FROM crawl_runs
            WHERE user_id = :user_id
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {"user_id": user_id},
    )
    run_error_log = run_error_log_result.scalar_one()
    scholar_result = run_error_log["scholar_results"][0]
    assert scholar_result["attempt_count"] == 2
    assert scholar_result["state"] == "ok"
    assert scholar_result["state_reason"] == "publications_extracted"


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_ingestion_rejects_overlapping_run_lock(
    db_session: AsyncSession,
    database_url: str,
) -> None:
    user_id = await insert_user(
        db_session,
        email="lock@example.com",
        password="ingest-password",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name, is_enabled)
            VALUES (:user_id, :scholar_id, :display_name, :is_enabled)
            """
        ),
        {
            "user_id": user_id,
            "scholar_id": "abcDEF123456",
            "display_name": "Lock Fixture",
            "is_enabled": True,
        },
    )
    await db_session.commit()

    engine = create_async_engine(database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    lock_session = factory()
    try:
        await lock_session.execute(
            text("SELECT pg_advisory_lock(:namespace, :user_key)"),
            {
                "namespace": RUN_LOCK_NAMESPACE,
                "user_key": user_id,
            },
        )

        service = ScholarIngestionService(
            source=CountingScholarSourceResults(
                [
                    FetchResult(
                        requested_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                        status_code=200,
                        final_url="https://scholar.google.com/citations?hl=en&user=abcDEF123456",
                        body=HTML_BASELINE,
                        error=None,
                    )
                ]
            )
        )
        with pytest.raises(RunAlreadyInProgressError):
            await service.run_for_user(
                db_session,
                user_id=user_id,
                trigger_type=RunTriggerType.MANUAL,
                request_delay_seconds=0,
                network_error_retries=0,
                retry_backoff_seconds=0,
            )
    finally:
        await lock_session.execute(
            text("SELECT pg_advisory_unlock(:namespace, :user_key)"),
            {
                "namespace": RUN_LOCK_NAMESPACE,
                "user_key": user_id,
            },
        )
        await lock_session.close()
        await engine.dispose()
