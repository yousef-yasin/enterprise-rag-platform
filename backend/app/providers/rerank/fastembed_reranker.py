"""fastembed cross-encoder reranker — the CPU default (docs/ARCHITECTURE.md section 13)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from functools import cached_property
from typing import Any

from app.core.errors import RerankError
from app.core.interfaces.reranker import RerankCandidate, RerankResult


class FastEmbedReranker:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    @cached_property
    def _model(self) -> Any:
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RerankError("fastembed cross-encoder support is unavailable") from exc
        return TextCrossEncoder(model_name=self.model_id)

    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], *, top_n: int
    ) -> list[RerankResult]:
        if not candidates:
            return []
        docs = [c.text for c in candidates]
        try:
            scores = await asyncio.to_thread(self._score, query, docs)
        except Exception as exc:
            raise RerankError(f"reranker failed: {exc}") from exc
        ranked = sorted(
            (
                RerankResult(id=c.id, score=float(s))
                for c, s in zip(candidates, scores, strict=True)
            ),
            key=lambda r: r.score,
            reverse=True,
        )
        return ranked[:top_n]

    def _score(self, query: str, docs: list[str]) -> list[float]:
        return list(self._model.rerank(query, docs))
