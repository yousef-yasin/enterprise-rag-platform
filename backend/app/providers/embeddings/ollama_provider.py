"""Ollama embeddings adapter (local, opt-in — docs/ARCHITECTURE.md section 16.4)."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from app.core.errors import EmbeddingError
from app.core.interfaces.embeddings import EmbeddingProfile

_DIMS = {"nomic-embed-text": 768, "mxbai-embed-large": 1024, "all-minilm": 384}


class OllamaEmbeddingProvider:
    def __init__(self, model_id: str, *, base_url: str, max_batch: int = 16) -> None:
        self._base_url = base_url.rstrip("/")
        self.max_batch = max_batch
        self.profile = EmbeddingProfile(
            provider="ollama",
            model_id=model_id,
            dimension=_DIMS.get(model_id, 768),
            max_tokens=2048,
            normalize=True,
            query_prefix=None,
            doc_prefix=None,
            tokenizer_id="ollama-approx",
            pooling="mean",
            supported_langs=("en",),
        )

    async def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=120) as client:
            for text in texts:
                try:
                    resp = await client.post(
                        f"{self._base_url}/api/embeddings",
                        json={"model": self.profile.model_id, "prompt": text},
                    )
                    resp.raise_for_status()
                    out.append([float(x) for x in resp.json()["embedding"]])
                except Exception as exc:
                    raise EmbeddingError(f"Ollama embeddings failed: {exc}") from exc
        return out

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(texts) if texts else []

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text]))[0]

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)
