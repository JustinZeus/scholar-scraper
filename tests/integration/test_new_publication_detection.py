from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.runtime_deps import get_scholar_source
from app.main import app
from app.services.scholar.source import FetchResult
from tests.integration.helpers import (
    api_csrf_headers,
    insert_user,
    login_user,
    wait_for_run_complete,
)

SCHOLAR_ID = "newPubDetc01"


def _build_profile_html(publications: list[dict[str, str]]) -> str:
    rows = []
    for pub in publications:
        rows.append(
            f"""
            <tr class="gsc_a_tr">
              <td class="gsc_a_t">
                <a class="gsc_a_at"
                   href="/citations?view_op=view_citation&amp;citation_for_view={SCHOLAR_ID}:{pub["cluster"]}"
                >{pub["title"]}</a>
                <div class="gs_gray">{pub.get("authors", "A Author")}</div>
                <div class="gs_gray">{pub.get("venue", "Some Venue")}</div>
              </td>
              <td class="gsc_a_c"><a class="gsc_a_ac">{pub.get("citations", "0")}</a></td>
              <td class="gsc_a_y"><span class="gsc_a_h">{pub.get("year", "2024")}</span></td>
            </tr>"""
        )
    count = len(publications)
    return f"""
    <html>
      <head>
        <meta property="og:image" content="https://images.example.com/detect.png" />
      </head>
      <body>
        <div id="gsc_prf_in">New Pub Detector</div>
        <span id="gsc_a_nn">Articles 1-{count}</span>
        <table>
          <tbody id="gsc_a_b">{"".join(rows)}
          </tbody>
        </table>
      </body>
    </html>
    """


INITIAL_PUBLICATIONS = [
    {"cluster": "aaa111", "title": "Existing Paper One", "year": "2023", "citations": "10"},
    {"cluster": "bbb222", "title": "Existing Paper Two", "year": "2022", "citations": "5"},
]

UPDATED_PUBLICATIONS = [
    *INITIAL_PUBLICATIONS,
    {"cluster": "ccc333", "title": "Brand New Paper Three", "year": "2025", "citations": "0"},
]


class _MutableScholarSource:
    """Source that serves different HTML per phase to simulate page changes."""

    def __init__(self, initial_html: str) -> None:
        self.html = initial_html

    async def fetch_profile_html(self, scholar_id: str) -> FetchResult:
        return self._result(scholar_id)

    async def fetch_profile_page_html(
        self,
        scholar_id: str,
        *,
        cstart: int,
        pagesize: int,
    ) -> FetchResult:
        return self._result(scholar_id)

    def _result(self, scholar_id: str) -> FetchResult:
        return FetchResult(
            requested_url=f"https://scholar.google.com/citations?hl=en&user={scholar_id}",
            status_code=200,
            final_url=f"https://scholar.google.com/citations?hl=en&user={scholar_id}",
            body=self.html,
            error=None,
        )


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.asyncio
async def test_new_publication_detected_after_page_change(
    db_session: AsyncSession,
) -> None:
    """Verify the fingerprint short-circuit lets new publications through.

    Phase 1: Initial scrape discovers 2 publications.
    Phase 2: Same page → skipped via no_change fingerprint.
    Phase 3: Page gains a 3rd publication → fingerprint differs,
             scrape runs and discovers the new entry.
    """
    await insert_user(db_session, email="new-pub-detect@example.com", password="api-password")

    source = _MutableScholarSource(_build_profile_html(INITIAL_PUBLICATIONS))
    app.dependency_overrides[get_scholar_source] = lambda: source
    try:
        with TestClient(app) as client:
            login_user(client, email="new-pub-detect@example.com", password="api-password")
            headers = api_csrf_headers(client)

            create_resp = client.post("/api/v1/scholars", json={"scholar_id": SCHOLAR_ID}, headers=headers)
            assert create_resp.status_code == 201

            # ── Phase 1: initial scrape ─────────────────────────────
            run1 = client.post(
                "/api/v1/runs/manual",
                headers={**headers, "Idempotency-Key": "detect-run-001"},
            )
            assert run1.status_code == 200
            run1_id = int(run1.json()["data"]["run_id"])
            run1_data = await wait_for_run_complete(client, run1_id)

            assert run1_data["scholar_results"][0]["outcome"] == "success"
            assert run1_data["scholar_results"][0]["publication_count"] == 2
            assert run1_data["scholar_results"][0].get("state_reason") != "no_change_initial_page_signature"

            pubs1 = client.get("/api/v1/publications?mode=latest").json()["data"]
            assert pubs1["total_count"] == 2
            assert all(p["is_new_in_latest_run"] for p in pubs1["publications"])

            # ── Phase 2: unchanged page → skipped ──────────────────
            run2 = client.post(
                "/api/v1/runs/manual",
                headers={**headers, "Idempotency-Key": "detect-run-002"},
            )
            assert run2.status_code == 200
            run2_id = int(run2.json()["data"]["run_id"])
            run2_data = await wait_for_run_complete(client, run2_id)

            assert run2_data["scholar_results"][0]["state_reason"] == "no_change_initial_page_signature"
            assert run2_data["scholar_results"][0]["publication_count"] == 0

            # ── Phase 3: new publication appears ────────────────────
            source.html = _build_profile_html(UPDATED_PUBLICATIONS)

            run3 = client.post(
                "/api/v1/runs/manual",
                headers={**headers, "Idempotency-Key": "detect-run-003"},
            )
            assert run3.status_code == 200
            run3_id = int(run3.json()["data"]["run_id"])
            run3_data = await wait_for_run_complete(client, run3_id)

            assert run3_data["scholar_results"][0]["outcome"] == "success"
            assert run3_data["scholar_results"][0].get("state_reason") != "no_change_initial_page_signature"
            assert run3_data["scholar_results"][0]["publication_count"] == 3

            pubs3 = client.get("/api/v1/publications?mode=latest").json()["data"]
            assert pubs3["total_count"] == 3

            titles = {p["title"] for p in pubs3["publications"]}
            assert "Brand New Paper Three" in titles

            new_pub = next(p for p in pubs3["publications"] if p["title"] == "Brand New Paper Three")
            assert new_pub["is_new_in_latest_run"] is True

            old_pubs = [p for p in pubs3["publications"] if p["title"] != "Brand New Paper Three"]
            for p in old_pubs:
                assert p["is_new_in_latest_run"] is False
    finally:
        app.dependency_overrides.pop(get_scholar_source, None)
