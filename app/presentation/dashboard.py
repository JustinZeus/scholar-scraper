from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from app.db.models import CrawlRun
from app.services.publications import UnreadPublicationItem

SECTION_TEMPLATES: tuple[str, ...] = (
    "dashboard/_run_controls.html",
    "dashboard/_unread_publications.html",
    "dashboard/_run_history.html",
)


@dataclass(frozen=True)
class RunControlsViewModel:
    request_delay_seconds: int
    queue_queued_count: int
    queue_retrying_count: int
    queue_dropped_count: int
    run_manual_action: str = "/runs/manual"
    mark_all_read_action: str = "/publications/mark-all-read"


@dataclass(frozen=True)
class UnreadPublicationViewModel:
    title: str
    scholar_label: str
    year_display: str
    citation_count: int
    venue_text: str | None
    pub_url: str | None


@dataclass(frozen=True)
class RunHistoryItemViewModel:
    run_id: int | None
    detail_url: str | None
    started_at_display: str
    status_label: str
    status_badge: str
    scholar_count: int
    new_publication_count: int


@dataclass(frozen=True)
class DashboardViewModel:
    section_templates: tuple[str, ...]
    run_controls: RunControlsViewModel
    unread_publications: list[UnreadPublicationViewModel]
    run_history: list[RunHistoryItemViewModel]


def build_dashboard_view_model(
    *,
    unread_publications: Sequence[UnreadPublicationItem],
    recent_runs: Sequence[CrawlRun],
    request_delay_seconds: int,
    queue_counts: dict[str, int] | None = None,
) -> DashboardViewModel:
    queue_counts = queue_counts or {}
    return DashboardViewModel(
        section_templates=SECTION_TEMPLATES,
        run_controls=RunControlsViewModel(
            request_delay_seconds=request_delay_seconds,
            queue_queued_count=int(queue_counts.get("queued", 0)),
            queue_retrying_count=int(queue_counts.get("retrying", 0)),
            queue_dropped_count=int(queue_counts.get("dropped", 0)),
        ),
        unread_publications=[
            UnreadPublicationViewModel(
                title=item.title,
                scholar_label=item.scholar_label,
                year_display=str(item.year) if item.year is not None else "-",
                citation_count=item.citation_count,
                venue_text=item.venue_text,
                pub_url=item.pub_url,
            )
            for item in unread_publications
        ],
        run_history=[
            RunHistoryItemViewModel(
                run_id=run.id,
                detail_url=f"/runs/{run.id}" if run.id is not None else None,
                started_at_display=_format_started_at(run.start_dt),
                status_label=run.status.value,
                status_badge=_status_badge(run.status.value),
                scholar_count=run.scholar_count,
                new_publication_count=run.new_pub_count,
            )
            for run in recent_runs
        ],
    )


def _status_badge(status: str) -> str:
    if status == "success":
        return "ok"
    if status == "failed":
        return "danger"
    return "warn"


def _format_started_at(dt: datetime) -> str:
    local_aware = dt.astimezone(timezone.utc)
    return local_aware.strftime("%Y-%m-%d %H:%M UTC")
