from __future__ import annotations

from html import unescape

from app.services.domains.scholar.parser_constants import TAG_RE


def normalize_space(value: str) -> str:
    return " ".join(unescape(value).split())


def strip_tags(value: str) -> str:
    return normalize_space(TAG_RE.sub(" ", value))


def attr_class(attrs: list[tuple[str, str | None]]) -> str:
    for name, raw_value in attrs:
        if name.lower() == "class":
            return raw_value or ""
    return ""


def attr_href(attrs: list[tuple[str, str | None]]) -> str | None:
    for name, raw_value in attrs:
        if name.lower() == "href":
            return raw_value
    return None


def attr_src(attrs: list[tuple[str, str | None]]) -> str | None:
    for name, raw_value in attrs:
        if name.lower() == "src":
            return raw_value
    return None


def build_absolute_scholar_url(path_or_url: str | None) -> str | None:
    if not path_or_url:
        return None
    from urllib.parse import urljoin

    return urljoin("https://scholar.google.com", path_or_url)
