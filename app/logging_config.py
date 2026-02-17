from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import sys
from typing import Any

from app.logging_context import get_request_id

DEFAULT_REDACT_FIELDS = {
    "authorization",
    "cookie",
    "csrf_token",
    "new_password",
    "password",
    "password_hash",
    "session",
    "session_secret_key",
}

_BASE_RECORD = logging.makeLogRecord({})
_STANDARD_RECORD_FIELDS = set(_BASE_RECORD.__dict__.keys()) | {"message", "asctime"}
_NOISY_RECORD_FIELDS = {"color_message"}


def parse_redact_fields(raw: str | None) -> set[str]:
    fields = {field.strip().lower() for field in (raw or "").split(",") if field.strip()}
    return DEFAULT_REDACT_FIELDS | fields


def configure_logging(
    *,
    level: str,
    log_format: str,
    redact_fields: set[str],
    include_uvicorn_access: bool,
) -> None:
    normalized_level = _normalize_level(level)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(normalized_level)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(normalized_level)
    handler.addFilter(RequestContextFilter())

    normalized_format = log_format.strip().lower()
    if normalized_format == "json":
        handler.setFormatter(JsonLogFormatter(redact_fields=redact_fields))
    else:
        handler.setFormatter(ConsoleLogFormatter(redact_fields=redact_fields))

    root_logger.addHandler(handler)

    # Route server/framework logs through our single root handler.
    for logger_name in ("uvicorn", "uvicorn.error"):
        framework_logger = logging.getLogger(logger_name)
        framework_logger.handlers.clear()
        framework_logger.propagate = True
        framework_logger.setLevel(normalized_level)

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = True
    access_logger.setLevel(normalized_level if include_uvicorn_access else logging.WARNING)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            request_id = get_request_id()
            if request_id:
                record.request_id = request_id
        return True


class JsonLogFormatter(logging.Formatter):
    def __init__(self, *, redact_fields: set[str]) -> None:
        super().__init__()
        self._redact_fields = {field.lower() for field in redact_fields}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _format_timestamp(record.created),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        payload.update(self._redact_mapping(_extra_fields(record)))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, default=str)

    def _redact_mapping(self, value: dict[str, Any]) -> dict[str, Any]:
        return {key: self._redact_value(key, item) for key, item in value.items()}

    def _redact_value(self, key: str, value: Any) -> Any:
        if key.lower() in self._redact_fields:
            return "[REDACTED]"
        if isinstance(value, dict):
            return {nested_key: self._redact_value(nested_key, nested_value) for nested_key, nested_value in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._redact_value(key, item) for item in value]
        return value


class ConsoleLogFormatter(logging.Formatter):
    def __init__(self, *, redact_fields: set[str]) -> None:
        super().__init__()
        self._json_formatter = JsonLogFormatter(redact_fields=redact_fields)

    def format(self, record: logging.LogRecord) -> str:
        payload = json.loads(self._json_formatter.format(record))
        timestamp = payload.get("timestamp", "")
        level = _short_level(payload.get("level", "info"))
        logger_name = str(payload.get("logger", "app"))
        event = str(payload.get("event", ""))

        parts = [timestamp, level, logger_name, event]

        request_id = payload.pop("request_id", None)
        method = payload.pop("method", None)
        path = payload.pop("path", None)
        status_code = payload.pop("status_code", None)
        duration_ms = payload.pop("duration_ms", None)

        if request_id:
            parts.append(f"rid={request_id}")
        if method and path:
            parts.append(f"{method} {path}")
        if status_code is not None:
            parts.append(str(status_code))
        if duration_ms is not None:
            parts.append(f"{duration_ms}ms")

        for key in sorted(payload.keys()):
            if key in {"timestamp", "level", "logger", "event", "exception"}:
                continue
            parts.append(f"{key}={payload[key]}")

        if "exception" in payload:
            parts.append(f"exception={payload['exception']}")

        return " | ".join(str(part) for part in parts if part)


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _STANDARD_RECORD_FIELDS or key.startswith("_"):
            continue
        if key in _NOISY_RECORD_FIELDS:
            continue
        extras[key] = value
    return extras


def _normalize_level(level: str) -> int:
    normalized = level.strip().upper()
    mapping = logging.getLevelNamesMapping()
    if normalized not in mapping:
        return logging.INFO
    return mapping[normalized]


def _format_timestamp(created_ts: float) -> str:
    dt = datetime.fromtimestamp(created_ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%SZ")


def _short_level(level: str) -> str:
    mapping = {
        "debug": "DBG",
        "info": "INF",
        "warning": "WRN",
        "error": "ERR",
        "critical": "CRT",
    }
    return mapping.get(level.lower(), level[:3].upper())
