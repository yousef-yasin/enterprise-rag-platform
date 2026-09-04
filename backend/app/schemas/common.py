"""Shared request/response primitives."""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_PAGE_LIMIT = 100


class Page[T](BaseModel):
    items: list[T]
    limit: int
    offset: int
    total: int | None = None
    has_more: bool = False


class PaginationParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=MAX_PAGE_LIMIT)
    offset: int = Field(default=0, ge=0)
