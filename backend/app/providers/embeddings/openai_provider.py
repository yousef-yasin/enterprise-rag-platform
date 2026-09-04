"""OpenAI embeddings adapter (hosted; opt-in, docs/ARCHITECTURE.md §16.4)."""

from __future__ import annotations

from collections.abc import Sequence
from functools import cached_property

from app.core.errors import EmbeddingError
from app.core.interfaces.embeddings import EmbeddingProfile

_MODEL_SPECS: dict[str, dict[str, int]] = {
    "text-embedding-3-small": {"dimension": 1536, "max_tokens": 8191},
    "text-embedding-3-large": {"dimension": 3072, "max_tokens": 8191},
}


class OpenAIEmbeddingProvider:
    def __init__(
        self, model_id: str, *, api_key: str, base_url: str | None = None, max_batch: int = 128
    ) -> None:
        if model_id not in _MODEL_SPECS:
            raise EmbeddingError(f"unknown OpenAI embedding model {model_id!r}")
        spec = _MODEL_SPECS[model_id]
        self._api_key = api_key
        self._base_url = base_url
        self.max_batch = max_batch
        self.profile = EmbeddingProfile(
            provider="openai",
            model_id=model_id,
            dimension=spec["dimension"],
            max_tokens=spec["max_tokens"],
            normalize=True,
            query_prefix=None,
            doc_prefix=None,
            tokenizer_id="cl100k_base",
            pooling="mean",
            supported_langs=("en", "multi"),
        )

    @cached_property
    def _client(self) -> object:
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)

    @cached_property
    def _encoder(self) -> object:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")

    async def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            resp = await self._client.embeddings.create(  # type: ignore[attr-defined]
                model=self.profile.model_id, input=list(texts)
            )
        except Exception as exc:  # pragma: no cover - network
            raise EmbeddingError(f"OpenAI embeddings failed: {exc}") from exc
        return [item.embedding for item in resp.data]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(texts) if texts else []

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text]))[0]

    def count_tokens(self, text: str) -> int:
        return len(self._encoder.encode(text))  # type: ignore[attr-defined]
