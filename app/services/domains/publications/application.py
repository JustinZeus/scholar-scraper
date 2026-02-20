from __future__ import annotations

from app.services.domains.publications.counts import (
    count_for_user,
    count_latest_for_user,
    count_unread_for_user,
)
from app.services.domains.publications.listing import (
    list_for_user,
    list_new_for_latest_run_for_user,
    list_unread_for_user,
)
from app.services.domains.publications.modes import (
    MODE_ALL,
    MODE_LATEST,
    MODE_NEW,
    MODE_UNREAD,
    resolve_mode,
    resolve_publication_view_mode,
)
from app.services.domains.publications.queries import (
    get_latest_completed_run_id_for_user,
    publications_query,
)
from app.services.domains.publications.read_state import (
    mark_all_unread_as_read_for_user,
    mark_selected_as_read_for_user,
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
    "resolve_mode",
    "get_latest_completed_run_id_for_user",
    "publications_query",
    "list_for_user",
    "list_unread_for_user",
    "list_new_for_latest_run_for_user",
    "count_for_user",
    "count_unread_for_user",
    "count_latest_for_user",
    "mark_all_unread_as_read_for_user",
    "mark_selected_as_read_for_user",
]
