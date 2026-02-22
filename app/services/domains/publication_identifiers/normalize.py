from __future__ import annotations

import re
from urllib.parse import urlparse

from app.services.domains.doi.normalize import normalize_doi
from app.services.domains.publication_identifiers.types import IdentifierKind

ARXIV_ABS_RE = re.compile(r"\barxiv:\s*([a-z-]+/\d{7}|\d{4}\.\d{4,5})(v\d+)?\b", re.I)
ARXIV_PATH_RE = re.compile(r"^/(?:abs|pdf)/([a-z-]+/\d{7}|\d{4}\.\d{4,5})(v\d+)?(?:\.pdf)?/?$", re.I)
PMCID_RE = re.compile(r"\b(PMC\d+)\b", re.I)
PUBMED_PATH_RE = re.compile(r"^/(\d+)/?$")


def normalize_identifier(kind: IdentifierKind, value: str | None) -> str | None:
    if kind == IdentifierKind.DOI:
        return normalize_doi(value)
    if kind == IdentifierKind.ARXIV:
        return normalize_arxiv_id(value)
    if kind == IdentifierKind.PMCID:
        return normalize_pmcid(value)
    if kind == IdentifierKind.PMID:
        return normalize_pmid(value)
    return None


def normalize_arxiv_id(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and "arxiv.org" in parsed.netloc.lower():
        return _arxiv_from_path(parsed.path)
    match = ARXIV_ABS_RE.search(text)
    if not match:
        return None
    version = (match.group(2) or "").lower()
    return f"{match.group(1).lower()}{version}"


def _arxiv_from_path(path: str) -> str | None:
    match = ARXIV_PATH_RE.match(path or "")
    if not match:
        return None
    version = (match.group(2) or "").lower()
    return f"{match.group(1).lower()}{version}"


def normalize_pmcid(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and "ncbi.nlm.nih.gov" in parsed.netloc.lower():
        return _first_match(PMCID_RE, parsed.path)
    return _first_match(PMCID_RE, text)


def normalize_pmid(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and "pubmed.ncbi.nlm.nih.gov" in parsed.netloc.lower():
        match = PUBMED_PATH_RE.match(parsed.path or "")
        if not match:
            return None
        return match.group(1)
    return None


def _first_match(pattern: re.Pattern[str], value: str) -> str | None:
    match = pattern.search(value)
    if not match:
        return None
    return match.group(1).upper()
