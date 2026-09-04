"""Identity reranker (docs/ARCHITECTURE.md section 13)."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.interfaces.reranker import RerankCandidate, RerankResult


class NoOpReranker:
    model_id = "noop"

    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], *, top_n: int
    ) -> list[RerankResult]:
        # preserve incoming (fusion) order, descending synthetic score
        return [
            RerankResult(id=c.id, score=1.0 - i / max(len(candidates), 1))
            for i, c in enumerate(candidates[:top_n])
        ]
