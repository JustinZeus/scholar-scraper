from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from starlette.requests import Request
from starlette.responses import JSONResponse


def _request_id(request: Request) -> str | None:
    request_state = getattr(request, "state", None)
    if request_state is None:
        return None
    return getattr(request_state, "request_id", None)


def success_payload(
    request: Request,
    *,
    data: Any,
) -> dict[str, Any]:
    return {
        "data": data,
        "meta": {
            "request_id": _request_id(request),
        },
    }


def success_response(
    request: Request,
    *,
    data: Any,
    status_code: int = 200,
) -> JSONResponse:
    payload = success_payload(request, data=data)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(payload),
    )


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
) -> JSONResponse:
    payload = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
        "meta": {
            "request_id": _request_id(request),
        },
    }
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(payload),
    )
