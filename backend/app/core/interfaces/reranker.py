"""Reranker abstraction (docs/ARCHITECTURE.md §13). Adapters land in Phase 5."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RerankCandidate:
    id: str
    text: str


@dataclass(frozen=True, slots=True)
class RerankResult:
    id: str
    score: float


@runtime_checkable
class Reranker(Protocol):
    model_id: str

    async def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        *,
        top_n: int,
    ) -> list[RerankResult]:
        """Re-score and truncate to ``top_n``, ordered best-first. Callers apply the
        timeout and the fall-back-to-fusion-order policy (§13)."""
        ...
