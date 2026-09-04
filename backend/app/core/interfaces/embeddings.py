"""Embedding provider abstraction (docs/ARCHITECTURE.md §16). Adapters land in Phase 3."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    """Everything that makes two vectors comparable. Combined with the chunk policy
    this yields the ``embedding_profile_id`` that names a KB's Qdrant collection and
    gates cross-profile reads/writes (§16.3)."""

    provider: str
    model_id: str
    dimension: int
    max_tokens: int  # model max sequence length; drives chunk sizing (§11.1)
    normalize: bool
    query_prefix: str | None
    doc_prefix: str | None
    tokenizer_id: str
    pooling: Literal["cls", "mean"]
    supported_langs: tuple[str, ...]


@runtime_checkable
class EmbeddingProvider(Protocol):
    profile: EmbeddingProfile
    max_batch: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed passages. Applies ``profile.doc_prefix``."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a query. Applies ``profile.query_prefix`` (query/doc asymmetry, §16.2)."""
        ...

    def count_tokens(self, text: str) -> int:
        """Exact token count using ``profile.tokenizer_id``."""
        ...
