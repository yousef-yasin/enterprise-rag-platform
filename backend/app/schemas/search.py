"""Search + chat DTOs (docs/ARCHITECTURE.md section 23.1)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.core.enums import RetrievalMode


class RetrievalParams(BaseModel):
    mode: RetrievalMode = RetrievalMode.HYBRID
    dense_top_k: int | None = Field(default=None, ge=1, le=200)
    sparse_top_k: int | None = Field(default=None, ge=1, le=200)
    rerank_output_k: int | None = Field(default=None, ge=1, le=50)


class SearchRequest(BaseModel):
    knowledge_base_id: uuid.UUID
    query: str = Field(min_length=1, max_length=4000)
    params: RetrievalParams = RetrievalParams()
    include_trace: bool = False


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    score: float
    filename: str
    page_no: int | None
    snippet: str
    section_path: list[str]


class SearchResponse(BaseModel):
    search_query: str
    mode: RetrievalMode
    hits: list[SearchHit]
    abstained: bool
    low_confidence: bool
    degraded: dict[str, bool]
    fusion_strategy: str
    trace: dict[str, object] | None = None


class ChatRequest(BaseModel):
    knowledge_base_id: uuid.UUID
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: uuid.UUID | None = None
    params: RetrievalParams = RetrievalParams()


class CitationOut(BaseModel):
    index: int
    chunk_id: str | None
    document_id: str | None
    filename: str
    page_no: int | None
    snippet: str
    was_cited: bool
    weak: bool
    score: float | None


class ChatResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    conversation_id: str | None
    message_id: str | None
    trace_id: str | None
    abstained: bool
    low_confidence: bool
    degraded: dict[str, bool]
    uncited_sentences: list[str]
    usage: dict[str, int]
    cost_usd: float
