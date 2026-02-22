from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from typing import TYPE_CHECKING

from crossref.restful import Etiquette, Works

from app.services.domains.doi.normalize import normalize_doi
from app.settings import settings

if TYPE_CHECKING:
    from app.services.domains.publications.types import PublicationListItem, UnreadPublicationItem

TOKEN_RE = re.compile(r"[a-z0-9]+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9\\s]+")
STOP_WORDS = {"the", "and", "for", "with", "from", "method", "study", "analysis"}
_RATE_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
logger = logging.getLogger(__name__)
STRICT_TITLE_MATCH_THRESHOLD = 0.75
RELAXED_TITLE_MATCH_THRESHOLD = 0.85


def _rate_limit_wait(min_interval_seconds: float) -> None:
    global _LAST_REQUEST_AT
    interval = max(float(min_interval_seconds), 0.0)
    with _RATE_LOCK:
        elapsed = time.monotonic() - _LAST_REQUEST_AT
        remaining = interval - elapsed
        if remaining > 0:
            time.sleep(remaining)
        _LAST_REQUEST_AT = time.monotonic()


def _normalized_tokens(value: str) -> list[str]:
    lowered = value.lower().replace("’", "'").replace("“", "\"").replace("”", "\"")
    lowered = NON_ALNUM_RE.sub(" ", lowered)
    return [token for token in TOKEN_RE.findall(lowered) if len(token) >= 3]


def _normalized_query(value: str) -> str:
    tokens = [token for token in _normalized_tokens(value) if token not in STOP_WORDS]
    if len(tokens) < 3:
        tokens = _normalized_tokens(value)
    if len(tokens) < 3:
        return ""
    return " ".join(tokens[:12]).strip()


def _query_author(value: str) -> str | None:
    tokens = [token for token in value.strip().split() if token]
    if len(tokens) < 2:
        return None
    return " ".join(tokens[:2])[:64]


def _author_surname(value: str) -> str | None:
    tokens = [token for token in value.strip().split() if token]
    if not tokens:
        return None
    return NON_ALNUM_RE.sub("", tokens[-1].lower()) or None


def _query_filters(year: int | None) -> list[tuple[str, str] | None]:
    if year is None:
        return [None]
    return [
        (f"{year - 1}-01-01", f"{year + 1}-12-31"),
        (f"{year}-01-01", f"{year}-12-31"),
        None,
    ]


def _candidate_title(item: dict) -> str:
    titles = item.get("title")
    if isinstance(titles, list) and titles:
        return str(titles[0] or "")
    return str(item.get("title") or "")


def _title_match_score(source: str, candidate: str) -> float:
    source_tokens = {token for token in _normalized_tokens(source) if len(token) >= 3}
    candidate_tokens = {token for token in _normalized_tokens(candidate) if len(token) >= 3}
    if not source_tokens or not candidate_tokens:
        return 0.0
    return len(source_tokens & candidate_tokens) / float(len(source_tokens))


def _candidate_year(item: dict) -> int | None:
    issued = item.get("issued")
    if not isinstance(issued, dict):
        return None
    date_parts = issued.get("date-parts")
    if not isinstance(date_parts, list) or not date_parts:
        return None
    first = date_parts[0]
    if not isinstance(first, list) or not first:
        return None
    try:
        return int(first[0])
    except (TypeError, ValueError):
        return None


def _candidate_author_match(item: dict, surname: str | None) -> bool:
    if not surname:
        return True
    authors = item.get("author")
    if not isinstance(authors, list):
        return False
    for author in authors:
        if not isinstance(author, dict):
            continue
        family = NON_ALNUM_RE.sub("", str(author.get("family") or "").lower())
        if family and family == surname:
            return True
    return False


def _candidate_rank(*, title: str, year: int | None, item: dict) -> tuple[float, str | None]:
    doi = normalize_doi(str(item.get("DOI") or ""))
    if doi is None:
        return 0.0, None
    score = _title_match_score(title, _candidate_title(item))
    candidate_year = _candidate_year(item)
    if year is not None and candidate_year is not None:
        if abs(year - candidate_year) > 1:
            return 0.0, None
        score += 0.1
    return score, doi


def _year_delta(source_year: int | None, candidate_year: int | None) -> int | None:
    if source_year is None or candidate_year is None:
        return None
    return abs(int(source_year) - int(candidate_year))


def _candidate_rank_relaxed(
    *,
    title: str,
    year: int | None,
    item: dict,
    author_surname: str | None,
) -> tuple[float, str | None]:
    doi = normalize_doi(str(item.get("DOI") or ""))
    if doi is None:
        return 0.0, None
    score = _title_match_score(title, _candidate_title(item))
    if score <= 0:
        return 0.0, None
    candidate_year = _candidate_year(item)
    delta = _year_delta(year, candidate_year)
    if delta is not None:
        if delta <= 1:
            score += 0.05
        elif delta <= 3:
            score += 0.0
        elif delta <= 5:
            score -= 0.03
        else:
            score -= 0.08
    if _candidate_author_match(item, author_surname):
        score += 0.03
    return score, doi


def _best_candidate_doi_strict(
    *,
    title: str,
    year: int | None,
    items: list[dict],
    author_surname: str | None,
) -> str | None:
    best_score = 0.0
    best_doi: str | None = None
    best_year: int | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        if not _candidate_author_match(item, author_surname):
            continue
        score, doi = _candidate_rank(title=title, year=year, item=item)
        candidate_year = _candidate_year(item)
        if doi is None or score < STRICT_TITLE_MATCH_THRESHOLD:
            continue
        if score > best_score:
            best_score = score
            best_doi = doi
            best_year = candidate_year
            continue
        if abs(score - best_score) > 0.02:
            continue
        if best_year is None or candidate_year is None:
            continue
        if candidate_year < best_year:
            best_doi = doi
            best_year = candidate_year
    return best_doi


def _best_candidate_doi_relaxed(
    *,
    title: str,
    year: int | None,
    items: list[dict],
    author_surname: str | None,
) -> str | None:
    best_score = 0.0
    best_doi: str | None = None
    best_author_match = False
    best_delta: int | None = None
    best_year: int | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        score, doi = _candidate_rank_relaxed(
            title=title,
            year=year,
            item=item,
            author_surname=author_surname,
        )
        if doi is None or score < RELAXED_TITLE_MATCH_THRESHOLD:
            continue
        candidate_year = _candidate_year(item)
        candidate_author_match = _candidate_author_match(item, author_surname)
        candidate_delta = _year_delta(year, candidate_year)
        if score > best_score:
            best_score = score
            best_doi = doi
            best_author_match = candidate_author_match
            best_delta = candidate_delta
            best_year = candidate_year
            continue
        if abs(score - best_score) > 0.02:
            continue
        if candidate_author_match and not best_author_match:
            best_doi = doi
            best_author_match = True
            best_delta = candidate_delta
            best_year = candidate_year
            continue
        if best_delta is None and candidate_delta is not None:
            best_doi = doi
            best_author_match = candidate_author_match
            best_delta = candidate_delta
            best_year = candidate_year
            continue
        if best_delta is not None and candidate_delta is not None and candidate_delta < best_delta:
            best_doi = doi
            best_author_match = candidate_author_match
            best_delta = candidate_delta
            best_year = candidate_year
            continue
        if best_year is None or candidate_year is None:
            continue
        if candidate_year < best_year:
            best_doi = doi
            best_author_match = candidate_author_match
            best_delta = candidate_delta
            best_year = candidate_year
    return best_doi


def _best_candidate_doi(
    *,
    title: str,
    year: int | None,
    items: list[dict],
    author_surname: str | None,
) -> str | None:
    strict_match = _best_candidate_doi_strict(
        title=title,
        year=year,
        items=items,
        author_surname=author_surname,
    )
    if strict_match:
        return strict_match
    return _best_candidate_doi_relaxed(
        title=title,
        year=year,
        items=items,
        author_surname=author_surname,
    )


def _works_client(email: str | None) -> Works:
    if email:
        etiquette = Etiquette(settings.app_name, "0.1.0", "https://scholarr.local", email)
        return Works(etiquette=etiquette)
    return Works()


def _fetch_items_sync(
    *,
    query: str,
    author: str | None,
    date_range: tuple[str, str] | None,
    max_rows: int,
    email: str | None,
    min_interval_seconds: float,
) -> list[dict]:
    _rate_limit_wait(min_interval_seconds)
    works = _works_client(email)
    params = {"bibliographic": query}
    if author:
        params["author"] = author
    request = works.query(**params)
    if date_range is not None:
        from_date, until_date = date_range
        request = request.filter(from_pub_date=from_date, until_pub_date=until_date)
    request = request.select(["DOI", "title", "issued", "score", "author"])
    items: list[dict] = []
    for entry in request:
        if isinstance(entry, dict):
            items.append(entry)
        if len(items) >= max(max_rows, 1):
            break
    return items


async def _fetch_items(
    *,
    query: str,
    author: str | None,
    date_range: tuple[str, str] | None,
    max_rows: int,
    email: str | None,
) -> list[dict]:
    timeout = max(float(settings.crossref_timeout_seconds), 0.5)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _fetch_items_sync,
                query=query,
                author=author,
                date_range=date_range,
                max_rows=max_rows,
                email=email,
                min_interval_seconds=settings.crossref_min_interval_seconds,
            ),
            timeout=timeout,
        )
    except Exception:
        return []


async def discover_doi_for_publication(
    *,
    item: PublicationListItem | UnreadPublicationItem,
    max_rows: int = 10,
    email: str | None = None,
) -> str | None:
    title = (item.title or "").strip()
    query = _normalized_query(title)
    if not query:
        return None
    author = _query_author(item.scholar_label)
    author_surname = _author_surname(item.scholar_label)
    for date_range in _query_filters(item.year):
        items = await _fetch_items(
            query=query,
            author=author,
            date_range=date_range,
            max_rows=max_rows,
            email=email,
        )
        doi = _best_candidate_doi(
            title=title,
            year=item.year,
            items=items,
            author_surname=author_surname,
        )
        if doi:
            logger.debug("crossref.doi_discovered", extra={"event": "crossref.doi_discovered"})
            return doi
    return None
