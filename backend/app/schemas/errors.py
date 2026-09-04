"""Error-envelope response model (docs/ARCHITECTURE.md §23.3)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

ErrorCode = str  # closed enum documented in §23.3; kept as str until the API grows


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
