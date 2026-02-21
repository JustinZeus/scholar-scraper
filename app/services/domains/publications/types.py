from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PublicationListItem:
    publication_id: int
    scholar_profile_id: int
    scholar_label: str
    title: str
    year: int | None
    citation_count: int
    venue_text: str | None
    pub_url: str | None
    doi: str | None
    pdf_url: str | None
    is_read: bool
    first_seen_at: datetime
    is_new_in_latest_run: bool
    is_favorite: bool = False
    pdf_status: str = "untracked"
    pdf_attempt_count: int = 0
    pdf_failure_reason: str | None = None
    pdf_failure_detail: str | None = None


@dataclass(frozen=True)
class UnreadPublicationItem:
    publication_id: int
    scholar_profile_id: int
    scholar_label: str
    title: str
    year: int | None
    citation_count: int
    venue_text: str | None
    pub_url: str | None
    doi: str | None
    pdf_url: str | None
