"""Exception -> error-envelope mapping (docs/ARCHITECTURE.md §23.3, §31).

Every response body on an error path is ``{"error": {code, message, details,
request_id}}``. Stack traces are logged, never returned.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.context import current_request_id
from app.core.errors import AppError

_log = structlog.get_logger("app.api.errors")

_STATUS_CODE_MAP: dict[int, str] = {
    400: "validation_error",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    503: "internal",
}


def _envelope(
    code: str, message: str, *, status_code: int, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": current_request_id(),
            }
        },
    )


async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
    if exc.status_code >= 500:
        _log.warning("app_error", code=exc.code, status=exc.status_code, message=exc.message)
    return _envelope(exc.code, exc.message, status_code=exc.status_code, details=exc.details)


async def _handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return _envelope(
        "validation_error",
        "Request validation failed.",
        status_code=422,
        details={"errors": jsonable_encoder(exc.errors())},
    )


async def _handle_http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _STATUS_CODE_MAP.get(exc.status_code, "internal")
    message = exc.detail if isinstance(exc.detail, str) else "HTTP error."
    return _envelope(code, message, status_code=exc.status_code)


async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
    _log.exception("unhandled_exception", error=type(exc).__name__)
    return _envelope("internal", "An internal error occurred.", status_code=500)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _handle_unexpected)
