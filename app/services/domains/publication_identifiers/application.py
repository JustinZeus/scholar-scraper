from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Publication, PublicationIdentifier
from app.services.domains.doi.normalize import normalize_doi
from app.services.domains.publication_identifiers.normalize import (
    normalize_arxiv_id,
    normalize_pmcid,
    normalize_pmid,
)
from app.services.domains.publication_identifiers.types import (
    DisplayIdentifier,
    IdentifierCandidate,
    IdentifierKind,
)

if TYPE_CHECKING:
    from app.services.domains.publications.pdf_queue import PdfQueueListItem
    from app.services.domains.publications.types import PublicationListItem

CONFIDENCE_HIGH = 0.98
CONFIDENCE_MEDIUM = 0.9
CONFIDENCE_LOW = 0.6
CONFIDENCE_FALLBACK = 0.4
PRIORITY_DOI = 400
PRIORITY_ARXIV = 300
PRIORITY_PMCID = 200
PRIORITY_PMID = 100


def derive_display_identifier_from_values(
    *,
    doi: str | None,
    pub_url: str | None = None,
    pdf_url: str | None = None,
) -> DisplayIdentifier | None:
    candidates = _fallback_candidates_from_values(doi=doi, pub_url=pub_url, pdf_url=pdf_url)
    return _best_display_identifier(candidates)


def _fallback_candidates_from_values(
    *,
    doi: str | None,
    pub_url: str | None,
    pdf_url: str | None,
) -> list[IdentifierCandidate]:
    values = [value for value in [pub_url, pdf_url] if value]
    candidates = []
    if doi:
        normalized_doi = normalize_doi(doi)
        if normalized_doi:
            candidates.append(_candidate(IdentifierKind.DOI, doi, normalized_doi, "legacy_doi", CONFIDENCE_HIGH, pub_url))
    candidates.extend(_url_identifier_candidates(values=values, source="legacy_urls"))
    return _dedup_candidates(candidates)


def _url_identifier_candidates(*, values: list[str], source: str) -> list[IdentifierCandidate]:
    candidates: list[IdentifierCandidate] = []
    for value in values:
        candidates.extend(_url_candidates_for_value(value=value, source=source))
    return candidates


def _url_candidates_for_value(*, value: str, source: str) -> list[IdentifierCandidate]:
    candidates: list[IdentifierCandidate] = []
    arxiv = normalize_arxiv_id(value)
    if arxiv:
        candidates.append(_candidate(IdentifierKind.ARXIV, value, arxiv, source, CONFIDENCE_MEDIUM, value))
    pmcid = normalize_pmcid(value)
    if pmcid:
        candidates.append(_candidate(IdentifierKind.PMCID, value, pmcid, source, CONFIDENCE_LOW, value))
    pmid = normalize_pmid(value)
    if pmid:
        candidates.append(_candidate(IdentifierKind.PMID, value, pmid, source, CONFIDENCE_FALLBACK, value))
    return candidates


def _candidate(
    kind: IdentifierKind,
    value_raw: str,
    value_normalized: str,
    source: str,
    confidence_score: float,
    evidence_url: str | None,
) -> IdentifierCandidate:
    return IdentifierCandidate(
        kind=kind,
        value_raw=value_raw,
        value_normalized=value_normalized,
        source=source,
        confidence_score=float(confidence_score),
        evidence_url=evidence_url,
    )


def _dedup_candidates(candidates: list[IdentifierCandidate]) -> list[IdentifierCandidate]:
    deduped: dict[tuple[str, str], IdentifierCandidate] = {}
    for candidate in candidates:
        key = (candidate.kind.value, candidate.value_normalized)
        current = deduped.get(key)
        if current is None or candidate.confidence_score > current.confidence_score:
            deduped[key] = candidate
    return list(deduped.values())


async def sync_identifiers_for_publication_fields(
    db_session: AsyncSession,
    *,
    publication: Publication,
) -> None:
    candidates = _publication_field_candidates(publication)
    await _upsert_publication_candidates(db_session, publication_id=int(publication.id), candidates=candidates)


def _publication_field_candidates(publication: Publication) -> list[IdentifierCandidate]:
    return _fallback_candidates_from_values(
        doi=publication.doi,
        pub_url=publication.pub_url,
        pdf_url=publication.pdf_url,
    )


async def sync_identifiers_for_publication_resolution(
    db_session: AsyncSession,
    *,
    publication: Publication,
    source: str | None,
) -> None:
    candidates = _publication_field_candidates(publication)
    rewritten = [_candidate_with_source(candidate, source=source) for candidate in candidates]
    await _upsert_publication_candidates(db_session, publication_id=int(publication.id), candidates=rewritten)


def _candidate_with_source(candidate: IdentifierCandidate, *, source: str | None) -> IdentifierCandidate:
    if not source:
        return candidate
    return IdentifierCandidate(
        kind=candidate.kind,
        value_raw=candidate.value_raw,
        value_normalized=candidate.value_normalized,
        source=source,
        confidence_score=candidate.confidence_score,
        evidence_url=candidate.evidence_url,
    )


async def _upsert_publication_candidates(
    db_session: AsyncSession,
    *,
    publication_id: int,
    candidates: list[IdentifierCandidate],
) -> None:
    for candidate in _dedup_candidates(candidates):
        await _upsert_publication_candidate(db_session, publication_id=publication_id, candidate=candidate)


async def _upsert_publication_candidate(
    db_session: AsyncSession,
    *,
    publication_id: int,
    candidate: IdentifierCandidate,
) -> None:
    existing = await _existing_identifier(
        db_session,
        publication_id=publication_id,
        kind=candidate.kind.value,
        value_normalized=candidate.value_normalized,
    )
    if existing is None:
        db_session.add(_new_identifier_row(publication_id=publication_id, candidate=candidate))
        return
    _merge_identifier_row(existing, candidate=candidate)


async def _existing_identifier(
    db_session: AsyncSession,
    *,
    publication_id: int,
    kind: str,
    value_normalized: str,
) -> PublicationIdentifier | None:
    result = await db_session.execute(
        select(PublicationIdentifier).where(
            PublicationIdentifier.publication_id == publication_id,
            PublicationIdentifier.kind == kind,
            PublicationIdentifier.value_normalized == value_normalized,
        )
    )
    return result.scalar_one_or_none()


def _new_identifier_row(
    *,
    publication_id: int,
    candidate: IdentifierCandidate,
) -> PublicationIdentifier:
    return PublicationIdentifier(
        publication_id=publication_id,
        kind=candidate.kind.value,
        value_raw=candidate.value_raw,
        value_normalized=candidate.value_normalized,
        source=candidate.source,
        confidence_score=candidate.confidence_score,
        evidence_url=candidate.evidence_url,
    )


def _merge_identifier_row(existing: PublicationIdentifier, *, candidate: IdentifierCandidate) -> None:
    if candidate.confidence_score >= float(existing.confidence_score):
        existing.value_raw = candidate.value_raw
        existing.source = candidate.source
        existing.confidence_score = candidate.confidence_score
        if candidate.evidence_url:
            existing.evidence_url = candidate.evidence_url


async def overlay_publication_items_with_display_identifiers(
    db_session: AsyncSession,
    *,
    items: list[PublicationListItem],
) -> list[PublicationListItem]:
    if not items:
        return []
    mapping = await _display_identifier_map(db_session, publication_ids=[item.publication_id for item in items])
    return [_overlay_publication_item(item, mapping.get(item.publication_id)) for item in items]


def _overlay_publication_item(
    item: PublicationListItem,
    display_identifier: DisplayIdentifier | None,
) -> PublicationListItem:
    fallback = display_identifier or derive_display_identifier_from_values(doi=item.doi, pub_url=item.pub_url, pdf_url=item.pdf_url)
    return replace(item, display_identifier=fallback)


async def overlay_pdf_queue_items_with_display_identifiers(
    db_session: AsyncSession,
    *,
    items: list[PdfQueueListItem],
) -> list[PdfQueueListItem]:
    if not items:
        return []
    mapping = await _display_identifier_map(db_session, publication_ids=[item.publication_id for item in items])
    return [_overlay_queue_item(item, mapping.get(item.publication_id)) for item in items]


def _overlay_queue_item(
    item: PdfQueueListItem,
    display_identifier: DisplayIdentifier | None,
) -> PdfQueueListItem:
    fallback = display_identifier or derive_display_identifier_from_values(doi=item.doi, pdf_url=item.pdf_url)
    return replace(item, display_identifier=fallback)


async def _display_identifier_map(
    db_session: AsyncSession,
    *,
    publication_ids: list[int],
) -> dict[int, DisplayIdentifier]:
    normalized_ids = sorted({int(value) for value in publication_ids if int(value) > 0})
    if not normalized_ids:
        return {}
    result = await db_session.execute(
        select(PublicationIdentifier).where(PublicationIdentifier.publication_id.in_(normalized_ids))
    )
    rows = list(result.scalars().all())
    return _best_display_identifier_map(rows)


def _best_display_identifier_map(rows: list[PublicationIdentifier]) -> dict[int, DisplayIdentifier]:
    grouped: dict[int, list[IdentifierCandidate]] = {}
    for row in rows:
        grouped.setdefault(int(row.publication_id), []).append(_candidate_from_row(row))
    return {
        publication_id: display
        for publication_id, display in (
            (publication_id, _best_display_identifier(candidates))
            for publication_id, candidates in grouped.items()
        )
        if display is not None
    }


def _candidate_from_row(row: PublicationIdentifier) -> IdentifierCandidate:
    return IdentifierCandidate(
        kind=IdentifierKind(str(row.kind)),
        value_raw=str(row.value_raw),
        value_normalized=str(row.value_normalized),
        source=str(row.source),
        confidence_score=float(row.confidence_score),
        evidence_url=row.evidence_url,
    )


def _best_display_identifier(candidates: list[IdentifierCandidate]) -> DisplayIdentifier | None:
    if not candidates:
        return None
    ordered = sorted(candidates, key=_display_sort_key, reverse=True)
    return _display_identifier_from_candidate(ordered[0])


def _display_sort_key(candidate: IdentifierCandidate) -> tuple[int, float]:
    return (_kind_priority(candidate.kind), float(candidate.confidence_score))


def _kind_priority(kind: IdentifierKind) -> int:
    if kind == IdentifierKind.DOI:
        return PRIORITY_DOI
    if kind == IdentifierKind.ARXIV:
        return PRIORITY_ARXIV
    if kind == IdentifierKind.PMCID:
        return PRIORITY_PMCID
    return PRIORITY_PMID


def _display_identifier_from_candidate(candidate: IdentifierCandidate) -> DisplayIdentifier:
    value = candidate.value_normalized
    return DisplayIdentifier(
        kind=candidate.kind.value,
        value=value,
        label=_display_label(candidate.kind, value),
        url=_identifier_url(candidate.kind, value),
        confidence_score=float(candidate.confidence_score),
    )


def _display_label(kind: IdentifierKind, value: str) -> str:
    if kind == IdentifierKind.DOI:
        return f"DOI: {value}"
    if kind == IdentifierKind.ARXIV:
        return f"arXiv: {value}"
    if kind == IdentifierKind.PMCID:
        return f"PMCID: {value}"
    return f"PMID: {value}"


def _identifier_url(kind: IdentifierKind, value: str) -> str | None:
    if kind == IdentifierKind.DOI:
        return f"https://doi.org/{value}"
    if kind == IdentifierKind.ARXIV:
        return f"https://arxiv.org/abs/{value}"
    if kind == IdentifierKind.PMCID:
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{value}/"
    if kind == IdentifierKind.PMID:
        return f"https://pubmed.ncbi.nlm.nih.gov/{value}/"
    return None
