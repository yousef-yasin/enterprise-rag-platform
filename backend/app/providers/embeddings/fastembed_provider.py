"""fastembed (ONNX, CPU) dense embeddings — the default (ADR 0004)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any, Literal

from app.core.errors import EmbeddingError
from app.core.interfaces.embeddings import EmbeddingProfile


@dataclass(frozen=True, slots=True)
class _Spec:
    dimension: int
    max_tokens: int
    pooling: Literal["cls", "mean"]
    query_prefix: str | None
    langs: tuple[str, ...]


_MODEL_SPECS: dict[str, _Spec] = {
    "BAAI/bge-small-en-v1.5": _Spec(
        384, 512, "cls", "Represent this sentence for searching relevant passages: ", ("en",)
    ),
    "BAAI/bge-base-en-v1.5": _Spec(
        768, 512, "cls", "Represent this sentence for searching relevant passages: ", ("en",)
    ),
    "sentence-transformers/all-MiniLM-L6-v2": _Spec(384, 256, "mean", None, ("en",)),
    "BAAI/bge-m3": _Spec(
        1024,
        8192,
        "cls",
        None,
        ("en", "de", "fr", "es", "it", "pt", "nl", "zh", "ja", "ko", "ru", "ar"),
    ),
}


class FastEmbedProvider:
    def __init__(self, model_id: str, *, max_batch: int = 64) -> None:
        if model_id not in _MODEL_SPECS:
            raise EmbeddingError(
                f"embedding model {model_id!r} is not in the fastembed catalogue; "
                f"known: {', '.join(sorted(_MODEL_SPECS))}"
            )
        spec = _MODEL_SPECS[model_id]
        self.max_batch = max_batch
        self.profile = EmbeddingProfile(
            provider="fastembed",
            model_id=model_id,
            dimension=spec.dimension,
            max_tokens=spec.max_tokens,
            normalize=True,
            query_prefix=spec.query_prefix,
            doc_prefix=None,
            tokenizer_id=model_id,
            pooling=spec.pooling,
            supported_langs=spec.langs,
        )

    @cached_property
    def _model(self) -> Any:
        from fastembed import TextEmbedding

        return TextEmbedding(model_name=self.profile.model_id)

    @cached_property
    def _tokenizer(self) -> Any:
        from tokenizers import Tokenizer

        return Tokenizer.from_pretrained(self.profile.model_id)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, list(texts), False)

    async def embed_query(self, text: str) -> list[float]:
        result = await asyncio.to_thread(self._embed_sync, [text], True)
        return result[0]

    def _embed_sync(self, texts: list[str], is_query: bool) -> list[list[float]]:
        model = self._model
        try:
            if is_query and hasattr(model, "query_embed"):
                vectors = model.query_embed(texts)
            else:
                vectors = model.embed(texts)
            return [v.tolist() for v in vectors]
        except Exception as exc:  # pragma: no cover - network / model errors
            raise EmbeddingError(f"fastembed failed: {exc}") from exc

    def count_tokens(self, text: str) -> int:
        try:
            return len(self._tokenizer.encode(text).ids)
        except Exception:  # pragma: no cover
            return max(1, len(text) // 4)
