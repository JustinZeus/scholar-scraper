from __future__ import annotations

import re

SCHOLAR_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{12}$")
MAX_IMAGE_URL_LENGTH = 2048
MAX_AUTHOR_SEARCH_LIMIT = 25

DEFAULT_AUTHOR_SEARCH_CACHE_MAX_ENTRIES = 512
DEFAULT_AUTHOR_SEARCH_BLOCKED_CACHE_TTL_SECONDS = 300
DEFAULT_AUTHOR_SEARCH_COOLDOWN_BLOCK_THRESHOLD = 1
DEFAULT_AUTHOR_SEARCH_COOLDOWN_SECONDS = 1800
DEFAULT_AUTHOR_SEARCH_MIN_INTERVAL_SECONDS = 3.0
DEFAULT_AUTHOR_SEARCH_INTERVAL_JITTER_SECONDS = 1.0
DEFAULT_AUTHOR_SEARCH_RETRY_ALERT_THRESHOLD = 2
DEFAULT_AUTHOR_SEARCH_COOLDOWN_REJECTION_ALERT_THRESHOLD = 3

AUTHOR_SEARCH_RUNTIME_STATE_KEY = "global"
AUTHOR_SEARCH_LOCK_NAMESPACE = 3901
AUTHOR_SEARCH_LOCK_KEY = 1

ALLOWED_IMAGE_UPLOAD_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

SEARCH_DISABLED_REASON = "search_disabled_by_configuration"
SEARCH_COOLDOWN_REASON = "search_temporarily_disabled_due_to_repeated_blocks"
SEARCH_CACHED_BLOCK_REASON = "search_temporarily_disabled_from_cached_blocked_response"

STATE_REASON_HINTS: dict[str, str] = {
    SEARCH_DISABLED_REASON: (
        "Scholar name search is currently disabled by service policy. "
        "Add scholars by profile URL or Scholar ID."
    ),
    SEARCH_COOLDOWN_REASON: (
        "Scholar name search is temporarily paused after repeated block responses. "
        "Use Scholar URL/ID adds until cooldown expires."
    ),
    SEARCH_CACHED_BLOCK_REASON: (
        "A recent blocked response was cached to reduce traffic. "
        "Retry later or add by Scholar URL/ID."
    ),
    "network_dns_resolution_failed": (
        "DNS resolution failed while reaching scholar.google.com. "
        "Verify container DNS/network and retry."
    ),
    "network_timeout": (
        "Request timed out before Google Scholar responded. "
        "Increase delay/backoff and retry."
    ),
    "network_tls_error": (
        "TLS handshake/certificate validation failed. "
        "Verify outbound TLS/network configuration."
    ),
    "blocked_http_429_rate_limited": (
        "Google Scholar rate-limited the request. "
        "Slow request cadence and retry later."
    ),
    "blocked_unusual_traffic_detected": (
        "Google Scholar flagged traffic as unusual. "
        "Increase delay/jitter and reduce concurrent scraping."
    ),
    "blocked_accounts_redirect": (
        "Request was redirected to Google Account sign-in. "
        "Treat as access block and retry later."
    ),
}
