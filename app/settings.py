from dataclasses import dataclass
import os

DEFAULT_SECURITY_PERMISSIONS_POLICY = (
    "accelerometer=(), autoplay=(), camera=(), display-capture=(), "
    "geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()"
)
DEFAULT_SECURITY_CSP_POLICY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "img-src 'self' data: https:; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'"
)
DEFAULT_SECURITY_CSP_DOCS_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data: https:; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; "
    "connect-src 'self' https:; "
    "object-src 'none'; "
    "frame-ancestors 'none'"
)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip() or default


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "scholarr")
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://scholar:scholar@db:5432/scholar",
    )
    session_secret_key: str = os.getenv("SESSION_SECRET_KEY", "dev-insecure-session-key")
    session_cookie_secure: bool = _env_bool("SESSION_COOKIE_SECURE", False)
    security_headers_enabled: bool = _env_bool("SECURITY_HEADERS_ENABLED", True)
    security_x_content_type_options: str = _env_str("SECURITY_X_CONTENT_TYPE_OPTIONS", "nosniff")
    security_x_frame_options: str = _env_str("SECURITY_X_FRAME_OPTIONS", "DENY")
    security_referrer_policy: str = _env_str("SECURITY_REFERRER_POLICY", "strict-origin-when-cross-origin")
    security_permissions_policy: str = _env_str(
        "SECURITY_PERMISSIONS_POLICY",
        DEFAULT_SECURITY_PERMISSIONS_POLICY,
    )
    security_cross_origin_opener_policy: str = _env_str(
        "SECURITY_CROSS_ORIGIN_OPENER_POLICY",
        "same-origin",
    )
    security_cross_origin_resource_policy: str = _env_str(
        "SECURITY_CROSS_ORIGIN_RESOURCE_POLICY",
        "same-origin",
    )
    security_csp_enabled: bool = _env_bool("SECURITY_CSP_ENABLED", True)
    security_csp_policy: str = _env_str("SECURITY_CSP_POLICY", DEFAULT_SECURITY_CSP_POLICY)
    security_csp_docs_policy: str = _env_str("SECURITY_CSP_DOCS_POLICY", DEFAULT_SECURITY_CSP_DOCS_POLICY)
    security_csp_report_only: bool = _env_bool("SECURITY_CSP_REPORT_ONLY", False)
    security_strict_transport_security_enabled: bool = _env_bool(
        "SECURITY_STRICT_TRANSPORT_SECURITY_ENABLED",
        False,
    )
    security_strict_transport_security_max_age: int = _env_int(
        "SECURITY_STRICT_TRANSPORT_SECURITY_MAX_AGE",
        31_536_000,
    )
    security_strict_transport_security_include_subdomains: bool = _env_bool(
        "SECURITY_STRICT_TRANSPORT_SECURITY_INCLUDE_SUBDOMAINS",
        True,
    )
    security_strict_transport_security_preload: bool = _env_bool(
        "SECURITY_STRICT_TRANSPORT_SECURITY_PRELOAD",
        False,
    )
    login_rate_limit_attempts: int = _env_int("LOGIN_RATE_LIMIT_ATTEMPTS", 5)
    login_rate_limit_window_seconds: int = _env_int(
        "LOGIN_RATE_LIMIT_WINDOW_SECONDS",
        60,
    )
    log_level: str = _env_str("LOG_LEVEL", "INFO")
    log_format: str = _env_str("LOG_FORMAT", "console")
    log_requests: bool = _env_bool("LOG_REQUESTS", True)
    log_uvicorn_access: bool = _env_bool("LOG_UVICORN_ACCESS", False)
    log_request_skip_paths: str = _env_str("LOG_REQUEST_SKIP_PATHS", "/healthz")
    log_redact_fields: str = os.getenv("LOG_REDACT_FIELDS", "")
    scheduler_enabled: bool = _env_bool("SCHEDULER_ENABLED", True)
    scheduler_tick_seconds: int = _env_int("SCHEDULER_TICK_SECONDS", 60)
    ingestion_network_error_retries: int = _env_int("INGESTION_NETWORK_ERROR_RETRIES", 1)
    ingestion_retry_backoff_seconds: float = _env_float(
        "INGESTION_RETRY_BACKOFF_SECONDS",
        1.0,
    )
    ingestion_max_pages_per_scholar: int = _env_int(
        "INGESTION_MAX_PAGES_PER_SCHOLAR",
        30,
    )
    ingestion_page_size: int = _env_int("INGESTION_PAGE_SIZE", 100)
    ingestion_alert_blocked_failure_threshold: int = _env_int(
        "INGESTION_ALERT_BLOCKED_FAILURE_THRESHOLD",
        1,
    )
    ingestion_alert_network_failure_threshold: int = _env_int(
        "INGESTION_ALERT_NETWORK_FAILURE_THRESHOLD",
        2,
    )
    ingestion_alert_retry_scheduled_threshold: int = _env_int(
        "INGESTION_ALERT_RETRY_SCHEDULED_THRESHOLD",
        3,
    )
    ingestion_continuation_queue_enabled: bool = _env_bool(
        "INGESTION_CONTINUATION_QUEUE_ENABLED",
        True,
    )
    ingestion_continuation_base_delay_seconds: int = _env_int(
        "INGESTION_CONTINUATION_BASE_DELAY_SECONDS",
        120,
    )
    ingestion_continuation_max_delay_seconds: int = _env_int(
        "INGESTION_CONTINUATION_MAX_DELAY_SECONDS",
        3600,
    )
    ingestion_continuation_max_attempts: int = _env_int(
        "INGESTION_CONTINUATION_MAX_ATTEMPTS",
        6,
    )
    scheduler_queue_batch_size: int = _env_int("SCHEDULER_QUEUE_BATCH_SIZE", 10)
    frontend_enabled: bool = _env_bool("FRONTEND_ENABLED", True)
    frontend_dist_dir: str = _env_str("FRONTEND_DIST_DIR", "/app/frontend/dist")
    scholar_image_upload_dir: str = _env_str(
        "SCHOLAR_IMAGE_UPLOAD_DIR",
        "/tmp/scholarr_uploads/scholar_images",
    )
    scholar_image_upload_max_bytes: int = _env_int(
        "SCHOLAR_IMAGE_UPLOAD_MAX_BYTES",
        2_000_000,
    )
    scholar_name_search_enabled: bool = _env_bool("SCHOLAR_NAME_SEARCH_ENABLED", True)
    scholar_name_search_cache_ttl_seconds: int = _env_int(
        "SCHOLAR_NAME_SEARCH_CACHE_TTL_SECONDS",
        21_600,
    )
    scholar_name_search_blocked_cache_ttl_seconds: int = _env_int(
        "SCHOLAR_NAME_SEARCH_BLOCKED_CACHE_TTL_SECONDS",
        300,
    )
    scholar_name_search_cache_max_entries: int = _env_int(
        "SCHOLAR_NAME_SEARCH_CACHE_MAX_ENTRIES",
        512,
    )
    scholar_name_search_min_interval_seconds: float = _env_float(
        "SCHOLAR_NAME_SEARCH_MIN_INTERVAL_SECONDS",
        8.0,
    )
    scholar_name_search_interval_jitter_seconds: float = _env_float(
        "SCHOLAR_NAME_SEARCH_INTERVAL_JITTER_SECONDS",
        2.0,
    )
    scholar_name_search_cooldown_block_threshold: int = _env_int(
        "SCHOLAR_NAME_SEARCH_COOLDOWN_BLOCK_THRESHOLD",
        1,
    )
    scholar_name_search_cooldown_seconds: int = _env_int(
        "SCHOLAR_NAME_SEARCH_COOLDOWN_SECONDS",
        1800,
    )
    scholar_name_search_alert_retry_count_threshold: int = _env_int(
        "SCHOLAR_NAME_SEARCH_ALERT_RETRY_COUNT_THRESHOLD",
        2,
    )
    scholar_name_search_alert_cooldown_rejections_threshold: int = _env_int(
        "SCHOLAR_NAME_SEARCH_ALERT_COOLDOWN_REJECTIONS_THRESHOLD",
        3,
    )


settings = Settings()
