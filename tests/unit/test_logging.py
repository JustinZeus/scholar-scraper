from __future__ import annotations

import json
import logging
import re

from fastapi.testclient import TestClient

from app.logging_config import JsonLogFormatter, parse_redact_fields
from app.main import app
from app.web.middleware import REQUEST_ID_HEADER, parse_skip_paths


def test_json_log_formatter_redacts_sensitive_fields() -> None:
    formatter = JsonLogFormatter(redact_fields=parse_redact_fields("api_key"))
    record = logging.makeLogRecord(
        {
            "name": "tests.logging",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "test.event",
            "args": (),
            "password": "very-secret",
            "payload": {
                "csrf_token": "token-value",
                "safe": "ok",
            },
            "color_message": "ANSI-noise",
        }
    )

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "test.event"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}Z", payload["timestamp"])
    assert payload["password"] == "[REDACTED]"
    assert payload["payload"]["csrf_token"] == "[REDACTED]"
    assert payload["payload"]["safe"] == "ok"
    assert "color_message" not in payload


def test_request_logging_middleware_sets_request_id_header() -> None:
    client = TestClient(app)

    response = client.get("/login", headers={REQUEST_ID_HEADER: "request-123"})

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "request-123"


def test_parse_skip_paths_trims_and_discards_empty_segments() -> None:
    assert parse_skip_paths(" /healthz , , /static/ ") == ("/healthz", "/static/")
