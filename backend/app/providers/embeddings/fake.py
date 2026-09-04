"""Deterministic fake embedder (tests / CI only, docs/ARCHITECTURE.md §16.4)."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from app.core.interfaces.embeddings import EmbeddingProfile

_DIM = 384

FAKE_PROFILE = EmbeddingProfile(
    provider="fake",
    model_id="fake-deterministic-384",
    dimension=_DIM,
    max_tokens=512,
    normalize=True,
    query_prefix="query: ",
    doc_prefix="passage: ",
    tokenizer_id="fake-chars-over-4",
    pooling="mean",
    supported_langs=("en",),
)


def _vector(text: str) -> list[float]:
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [0.0] * _DIM
    for i in range(_DIM):
        b = seed[i % len(seed)]
        raw[i] = ((b ^ (i * 31 + 7)) % 251) / 251.0 - 0.5
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


class FakeEmbedder:
    profile = FAKE_PROFILE
    max_batch = 64

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        prefix = self.profile.doc_prefix or ""
        return [_vector(prefix + t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return _vector((self.profile.query_prefix or "") + text)

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)
