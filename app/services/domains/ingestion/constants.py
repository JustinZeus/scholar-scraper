from __future__ import annotations

import re

from app.services.domains.scholar.parser import ParseState

TITLE_ALNUM_RE = re.compile(r"[^a-z0-9]+")
WORD_RE = re.compile(r"[a-z0-9]+")
HTML_TAG_RE = re.compile(r"<[^>]+>", re.S)
SPACE_RE = re.compile(r"\s+")

FAILED_STATES = {
    ParseState.BLOCKED_OR_CAPTCHA.value,
    ParseState.LAYOUT_CHANGED.value,
    ParseState.NETWORK_ERROR.value,
    "ingestion_error",
}

FAILURE_BUCKET_BLOCKED = "blocked_or_captcha"
FAILURE_BUCKET_NETWORK = "network_error"
FAILURE_BUCKET_LAYOUT = "layout_changed"
FAILURE_BUCKET_INGESTION = "ingestion_error"
FAILURE_BUCKET_OTHER = "other_failure"

RUN_LOCK_NAMESPACE = 8217
RESUMABLE_PARTIAL_REASONS = {
    "max_pages_reached",
    "pagination_cursor_stalled",
}
RESUMABLE_PARTIAL_REASON_PREFIXES = ("page_state_network_error",)
INITIAL_PAGE_FINGERPRINT_MAX_PUBLICATIONS = 30
