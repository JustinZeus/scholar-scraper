from __future__ import annotations

MODE_ALL = "all"
MODE_UNREAD = "unread"
MODE_LATEST = "latest"
MODE_NEW = "new"  # compatibility alias for MODE_LATEST


def resolve_publication_view_mode(value: str | None) -> str:
    if value == MODE_UNREAD:
        return MODE_UNREAD
    if value in {MODE_LATEST, MODE_NEW}:
        return MODE_LATEST
    return MODE_ALL
