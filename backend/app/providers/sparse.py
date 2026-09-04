"""BM25-style sparse encoding via fastembed (docs/ARCHITECTURE.md section 12).

Term frequencies are computed client-side (``Qdrant/bm25``); Qdrant applies IDF
server-side (``Modifier.IDF``). "BM25-style", not textbook BM25.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any

_MODEL = "Qdrant/bm25"


@dataclass(frozen=True, slots=True)
class SparseVector:
    indices: list[int]
    values: list[float]


class SparseEncoder:
    @cached_property
    def _model(self) -> Any:
        from fastembed import SparseTextEmbedding

        return SparseTextEmbedding(model_name=_MODEL)

    async def encode_documents(self, texts: Sequence[str]) -> list[SparseVector]:
        if not texts:
            return []
        return await asyncio.to_thread(self._encode, list(texts), False)

    async def encode_query(self, text: str) -> SparseVector:
        result = await asyncio.to_thread(self._encode, [text], True)
        return result[0]

    def _encode(self, texts: list[str], is_query: bool) -> list[SparseVector]:
        model = self._model
        gen = (
            model.query_embed(texts)
            if is_query and hasattr(model, "query_embed")
            else model.embed(texts)
        )
        out: list[SparseVector] = []
        for emb in gen:
            out.append(
                SparseVector(indices=list(emb.indices), values=[float(v) for v in emb.values])
            )
        return out


_encoder: SparseEncoder | None = None


def get_sparse_encoder() -> SparseEncoder:
    global _encoder
    if _encoder is None:
        _encoder = SparseEncoder()
    return _encoder
