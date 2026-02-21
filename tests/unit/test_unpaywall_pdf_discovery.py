from __future__ import annotations

import pytest

from app.services.domains.unpaywall import pdf_discovery


def test_looks_like_pdf_url_detects_path_and_query_variants() -> None:
    assert pdf_discovery.looks_like_pdf_url("https://example.org/file.pdf")
    assert pdf_discovery.looks_like_pdf_url("https://example.org/download?target=paper.pdf")
    assert not pdf_discovery.looks_like_pdf_url("https://example.org/landing")
    assert not pdf_discovery.looks_like_pdf_url(None)


def test_normalized_candidate_urls_extracts_and_resolves_relative_links() -> None:
    html = """
    <html>
      <head>
        <base href="https://publisher.example.org/articles/42/" />
        <meta name="citation_pdf_url" content="/pdfs/42-main.pdf" />
        <link rel="alternate" type="application/pdf" href="https://cdn.example.org/42-supp.pdf" />
      </head>
      <body>
        <a href="appendix.pdf">Appendix</a>
      </body>
    </html>
    """
    candidates = pdf_discovery._normalized_candidate_urls(
        page_url="https://publisher.example.org/articles/42",
        html=html,
    )
    assert len(candidates) == 3
    assert "https://cdn.example.org/42-supp.pdf" in candidates
    assert "https://publisher.example.org/pdfs/42-main.pdf" in candidates
    assert "https://publisher.example.org/articles/42/appendix.pdf" in candidates


def test_normalized_candidate_urls_extracts_plain_text_urls() -> None:
    html = """
    <html>
      <body>
        Footnote URL: http://www.mext.go.jp/component/english/file.pdf
      </body>
    </html>
    """
    candidates = pdf_discovery._normalized_candidate_urls(
        page_url="https://www.science.org/doi/10.1126/science.1239057",
        html=html,
    )
    assert "http://www.mext.go.jp/component/english/file.pdf" in candidates


class _FakeResponse:
    def __init__(self, *, status_code: int, content_type: str, text: str) -> None:
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.text = text


class _FakeClient:
    def __init__(self, pages: dict[str, _FakeResponse]) -> None:
        self._pages = pages

    async def get(self, url: str, follow_redirects: bool = True):  # noqa: ARG002
        return self._pages[url]


@pytest.mark.asyncio
async def test_resolve_pdf_from_landing_page_follows_one_hop_html_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _skip_wait(*args, **kwargs):  # noqa: ARG001, ANN002
        return None

    monkeypatch.setattr(pdf_discovery, "wait_for_unpaywall_slot", _skip_wait)
    landing_url = "https://example.org/article"
    hop_url = "https://example.org/doi/full/abc"
    pdf_url = "https://downloads.example.org/archive/paper.pdf"
    client = _FakeClient(
        {
            landing_url: _FakeResponse(
                status_code=200,
                content_type="text/html",
                text=f"<html><body><a href=\"{hop_url}\">View article</a></body></html>",
            ),
            hop_url: _FakeResponse(
                status_code=200,
                content_type="text/html",
                text=f"<html><body>Download here: {pdf_url}</body></html>",
            ),
        }
    )
    resolved = await pdf_discovery.resolve_pdf_from_landing_page(client, page_url=landing_url)
    assert resolved == pdf_url
