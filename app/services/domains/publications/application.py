from __future__ import annotations

from app.services.domains.publications.counts import (
    count_for_user,
    count_favorite_for_user,
    count_latest_for_user,
    count_unread_for_user,
)
from app.services.domains.publications.listing import (
    list_for_user,
    retry_pdf_for_user,
    list_unread_for_user,
)
from app.services.domains.publications.enrichment import (
    hydrate_pdf_enrichment_state,
    schedule_missing_pdf_enrichment_for_user,
    schedule_retry_pdf_enrichment_for_row,
)
from app.services.domains.publications.modes import (
    MODE_ALL,
    MODE_LATEST,
    MODE_NEW,
    MODE_UNREAD,
    resolve_publication_view_mode,
)
from app.services.domains.publications.queries import (
    get_latest_completed_run_id_for_user,
    get_publication_item_for_user,
    publications_query,
)
from app.services.domains.publications.read_state import (
    mark_all_unread_as_read_for_user,
    mark_selected_as_read_for_user,
    set_publication_favorite_for_user,
)
from app.services.domains.publications.pdf_queue import (
    count_pdf_queue_items,
    enqueue_all_missing_pdf_jobs,
    enqueue_retry_pdf_job_for_publication_id,
    list_pdf_queue_page,
    list_pdf_queue_items,
)
from app.services.domains.publications.types import PublicationListItem, UnreadPublicationItem

__all__ = [
    "MODE_ALL",
    "MODE_UNREAD",
    "MODE_LATEST",
    "MODE_NEW",
    "PublicationListItem",
    "UnreadPublicationItem",
    "resolve_publication_view_mode",
    "get_latest_completed_run_id_for_user",
    "publications_query",
    "get_publication_item_for_user",
    "list_for_user",
    "list_unread_for_user",
    "retry_pdf_for_user",
    "hydrate_pdf_enrichment_state",
    "schedule_retry_pdf_enrichment_for_row",
    "list_pdf_queue_items",
    "list_pdf_queue_page",
    "count_pdf_queue_items",
    "enqueue_all_missing_pdf_jobs",
    "enqueue_retry_pdf_job_for_publication_id",
    "schedule_missing_pdf_enrichment_for_user",
    "count_for_user",
    "count_favorite_for_user",
    "count_unread_for_user",
    "count_latest_for_user",
    "mark_all_unread_as_read_for_user",
    "mark_selected_as_read_for_user",
    "set_publication_favorite_for_user",
]
