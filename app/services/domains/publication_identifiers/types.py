from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IdentifierKind(StrEnum):
    DOI = "doi"
    ARXIV = "arxiv"
    PMCID = "pmcid"
    PMID = "pmid"


@dataclass(frozen=True)
class DisplayIdentifier:
    kind: str
    value: str
    label: str
    url: str | None
    confidence_score: float


@dataclass(frozen=True)
class IdentifierCandidate:
    kind: IdentifierKind
    value_raw: str
    value_normalized: str
    source: str
    confidence_score: float
    evidence_url: str | None
