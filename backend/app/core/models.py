"""Shared domain value objects (docs/ARCHITECTURE.md §3.2, §6, §8, §11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["heading", "paragraph", "list_item", "table", "code"]


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
        )


@dataclass(frozen=True, slots=True)
class DocumentBlock:
    """One structural unit from a parsed document (docs/ARCHITECTURE.md §8.2, §11.2)."""

    kind: BlockKind
    text: str
    level: int = 0  # heading depth (1..n); 0 for non-headings
    page_no: int | None = None
    char_start: int = 0
    char_end: int = 0


@dataclass(frozen=True, slots=True)
class DocumentTree:
    title: str
    blocks: tuple[DocumentBlock, ...]
    page_count: int | None
    lang: str | None
    total_chars: int


@dataclass(slots=True)
class ChunkSpec:
    """A chunk before embedding (docs/ARCHITECTURE.md §11)."""

    ordinal: int
    content: str
    embedding_input: str
    token_count: int
    section_path: list[str]
    page_no: int | None
    page_span_low: int | None
    page_span_high: int | None
    char_start: int
    char_end: int


@dataclass(slots=True)
class EmbeddedChunk:
    spec: ChunkSpec
    dense: list[float] | None
    ok: bool


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    """A retrieval candidate (docs/ARCHITECTURE.md §6)."""

    chunk_id: str
    document_id: str
    score: float
    content: str = ""
    filename: str = ""
    page_no: int | None = None
    ordinal: int = 0
    dense: tuple[float, ...] | None = None
    section_path: tuple[str, ...] = ()


@dataclass(slots=True)
class RetrievalDebug:
    dense_hits: list[dict[str, object]] = field(default_factory=list)
    sparse_hits: list[dict[str, object]] = field(default_factory=list)
    fused: list[dict[str, object]] = field(default_factory=list)
    reranked: list[dict[str, object]] = field(default_factory=list)
    degraded: dict[str, bool] = field(default_factory=dict)
    latency_ms: dict[str, float] = field(default_factory=dict)
