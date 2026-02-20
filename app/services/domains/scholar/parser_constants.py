from __future__ import annotations

import re

BLOCKED_KEYWORDS = [
    "unusual traffic",
    "sorry/index",
    "not a robot",
    "our systems have detected",
    "automated queries",
    "recaptcha",
    "captcha",
]

NO_RESULTS_KEYWORDS = [
    "didn't match any articles",
    "did not match any articles",
    "no articles",
    "no documents",
]

NO_AUTHOR_RESULTS_KEYWORDS = [
    "didn't match any user profiles",
    "did not match any user profiles",
    "didn't match any scholars",
    "did not match any scholars",
    "no user profiles",
]

MARKER_KEYS = [
    "gsc_a_tr",
    "gsc_a_at",
    "gsc_a_ac",
    "gsc_a_h",
    "gsc_a_y",
    "gs_gray",
    "gsc_prf_in",
    "gsc_rsb_st",
]

AUTHOR_SEARCH_MARKER_KEYS = [
    "gsc_1usr",
    "gs_ai_name",
    "gs_ai_aff",
    "gs_ai_eml",
    "gs_ai_cby",
    "gs_ai_one_int",
]

NETWORK_DNS_ERROR_KEYWORDS = [
    "temporary failure in name resolution",
    "name or service not known",
    "nodename nor servname provided",
    "getaddrinfo failed",
]

NETWORK_TIMEOUT_KEYWORDS = [
    "timed out",
    "timeout",
]

NETWORK_TLS_ERROR_KEYWORDS = [
    "ssl",
    "tls",
    "certificate verify failed",
]

TAG_RE = re.compile(r"<[^>]+>", re.S)
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
SHOW_MORE_BUTTON_RE = re.compile(
    r"<button\b[^>]*\bid\s*=\s*['\"]gsc_bpf_more['\"][^>]*>",
    re.I | re.S,
)

PROFILE_ROW_PARSER_DIRECT_MARKERS = (
    "gs_ggs",
    "gs_ggsd",
    "gs_ggsa",
    "gs_or_ggsm",
)

PROFILE_ROW_DIRECT_LABEL_TOKENS = (
    "pdf",
    "[pdf]",
    "full text",
    "download",
)
