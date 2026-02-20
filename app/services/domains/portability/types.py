from __future__ import annotations

from dataclasses import dataclass

from app.db.models import ScholarProfile


class ImportExportError(ValueError):
    """Raised when import/export payload constraints are violated."""


@dataclass(frozen=True)
class ImportedPublicationInput:
    profile: ScholarProfile
    title: str
    year: int | None
    citation_count: int
    author_text: str | None
    venue_text: str | None
    cluster_id: str | None
    pub_url: str | None
    doi: str | None
    pdf_url: str | None
    fingerprint: str
    is_read: bool
