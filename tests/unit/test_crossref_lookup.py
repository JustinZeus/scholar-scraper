from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.domains.crossref import application as crossref_app


def _item(*, title: str, year: int | None, scholar_label: str = "Shinya Yamanaka"):
    return SimpleNamespace(
        publication_id=1,
        scholar_label=scholar_label,
        title=title,
        year=year,
    )


@pytest.mark.asyncio
async def test_crossref_discovers_doi_from_best_title_match(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        [],
        [
            {
                "DOI": "10.1000/noisy",
                "title": ["Completely unrelated paper"],
                "issued": {"date-parts": [[2014]]},
                "author": [{"family": "Other"}],
            },
            {
                "DOI": "10.1016/j.cell.2007.11.019",
                "title": ["Induction of Pluripotent Stem Cells from Adult Human Fibroblasts"],
                "issued": {"date-parts": [[2007]]},
                "author": [{"family": "Yamanaka"}],
            },
        ],
    ]

    async def _fake_fetch_items(**_kwargs):
        return responses.pop(0) if responses else []

    monkeypatch.setattr(crossref_app, "_fetch_items", _fake_fetch_items)
    doi = await crossref_app.discover_doi_for_publication(
        item=_item(
            title="Induction of Pluripotent Stem Cells from Adult Human Fibroblasts",
            year=2007,
        ),
        max_rows=10,
        email="user@example.com",
    )
    assert doi == "10.1016/j.cell.2007.11.019"


@pytest.mark.asyncio
async def test_crossref_rejects_large_year_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_fetch_items(**_kwargs):
        return [
            {
                "DOI": "10.1000/wrong-year",
                "title": ["Induction of Pluripotent Stem Cells from Adult Human Fibroblasts"],
                "issued": {"date-parts": [[2014]]},
                "author": [{"family": "Yamanaka"}],
            }
        ]

    monkeypatch.setattr(crossref_app, "_fetch_items", _fake_fetch_items)
    doi = await crossref_app.discover_doi_for_publication(
        item=_item(
            title="Induction of Pluripotent Stem Cells from Adult Human Fibroblasts",
            year=2007,
        ),
        max_rows=10,
        email=None,
    )
    assert doi is None
