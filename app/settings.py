from dataclasses import dataclass
import os


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
        "/var/lib/scholarr/uploads",
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
        3.0,
    )
    scholar_name_search_interval_jitter_seconds: float = _env_float(
        "SCHOLAR_NAME_SEARCH_INTERVAL_JITTER_SECONDS",
        1.0,
    )
    scholar_name_search_cooldown_block_threshold: int = _env_int(
        "SCHOLAR_NAME_SEARCH_COOLDOWN_BLOCK_THRESHOLD",
        1,
    )
    scholar_name_search_cooldown_seconds: int = _env_int(
        "SCHOLAR_NAME_SEARCH_COOLDOWN_SECONDS",
        1800,
    )


settings = Settings()
