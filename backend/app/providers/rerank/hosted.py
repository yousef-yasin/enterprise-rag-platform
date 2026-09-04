"""Hosted reranker adapters — Cohere and Jina (docs/ARCHITECTURE.md section 13)."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from app.core.errors import RerankError
from app.core.interfaces.reranker import RerankCandidate, RerankResult


class _HostedReranker:
    _url: str

    def __init__(self, model_id: str, *, api_key: str) -> None:
        self.model_id = model_id
        self._api_key = api_key

    def _payload(self, query: str, docs: list[str], top_n: int) -> dict[str, object]:
        raise NotImplementedError

    def _parse(self, data: dict[str, object]) -> list[tuple[int, float]]:
        raise NotImplementedError

    async def rerank(
        self, query: str, candidates: Sequence[RerankCandidate], *, top_n: int
    ) -> list[RerankResult]:
        if not candidates:
            return []
        docs = [c.text for c in candidates]
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=self._payload(query, docs, top_n),
                )
                resp.raise_for_status()
                pairs = self._parse(resp.json())
        except Exception as exc:
            raise RerankError(f"{type(self).__name__} failed: {exc}") from exc
        return [RerankResult(id=candidates[i].id, score=score) for i, score in pairs][:top_n]


class CohereReranker(_HostedReranker):
    _url = "https://api.cohere.com/v2/rerank"

    def _payload(self, query: str, docs: list[str], top_n: int) -> dict[str, object]:
        return {"model": self.model_id, "query": query, "documents": docs, "top_n": top_n}

    def _parse(self, data: dict[str, object]) -> list[tuple[int, float]]:
        results = data.get("results", [])
        if not isinstance(results, list):
            return []
        out: list[tuple[int, float]] = []
        for r in results:
            if isinstance(r, dict):
                out.append((int(r["index"]), float(r["relevance_score"])))
        return out


class JinaReranker(_HostedReranker):
    _url = "https://api.jina.ai/v1/rerank"

    def _payload(self, query: str, docs: list[str], top_n: int) -> dict[str, object]:
        return {"model": self.model_id, "query": query, "documents": docs, "top_n": top_n}

    def _parse(self, data: dict[str, object]) -> list[tuple[int, float]]:
        results = data.get("results", [])
        if not isinstance(results, list):
            return []
        out: list[tuple[int, float]] = []
        for r in results:
            if isinstance(r, dict):
                out.append((int(r["index"]), float(r["relevance_score"])))
        return out
