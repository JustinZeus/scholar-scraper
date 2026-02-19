from app.services.scholar_source import _build_profile_url


def test_build_profile_url_includes_pagesize_for_initial_page() -> None:
    url = _build_profile_url(
        scholar_id="abcDEF123456",
        cstart=0,
        pagesize=100,
    )

    assert "user=abcDEF123456" in url
    assert "pagesize=100" in url
    assert "cstart=" not in url
