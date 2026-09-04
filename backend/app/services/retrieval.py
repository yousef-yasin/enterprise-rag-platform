"""Retrieval pipeline (docs/ARCHITECTURE.md sections 6, 11-14)."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

import structlog

from app.config import Settings
from app.core.embedding_profile import (
    ChunkPolicy,
    compute_embedding_profile_id,
    qdrant_collection_name,
)
from app.core.enums import RetrievalMode
from app.core.errors import ConflictError
from app.core.interfaces.embeddings import EmbeddingProvider
from app.core.interfaces.reranker import RerankCandidate, Reranker
from app.core.models import ScoredChunk
from app.core.retrieval.abstention import AbstentionDecision, decide
from app.core.retrieval.dedup import suppress_duplicates
from app.core.retrieval.fusion import Ranked, fuse
from app.infra.db.repositories.documents import ChunkRepository
from app.infra.db.session import session_scope
from app.infra.qdrant.store import QdrantVectorStore, RetrievalFilter
from app.obs.metrics import DEGRADED, record_retrieval_timings
from app.providers.registry import build_embedding_provider, build_reranker

_log = structlog.get_logger("app.retrieval")


@dataclass(slots=True)
class RetrievalResult:
    search_query: str
    mode: RetrievalMode
    candidates: list[ScoredChunk]
    abstention: AbstentionDecision
    fusion_strategy: str
    embedding_profile_id: str
    degraded: dict[str, bool] = field(default_factory=dict)
    latency_ms: dict[str, float] = field(default_factory=dict)
    dense_hits: list[dict[str, object]] = field(default_factory=list)
    sparse_hits: list[dict[str, object]] = field(default_factory=list)
    fused: list[dict[str, object]] = field(default_factory=list)
    reranked: list[dict[str, object]] = field(default_factory=list)


class RetrievalService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._embedder: EmbeddingProvider = build_embedding_provider(settings)
        self._reranker: Reranker | None = build_reranker(settings)

    @property
    def embedding_profile_id(self) -> str:
        return compute_embedding_profile_id(
            self._embedder.profile, ChunkPolicy.from_settings(self._settings)
        )

    async def retrieve(
        self,
        *,
        knowledge_base_id: uuid.UUID,
        kb_active_profile: str | None,
        search_query: str,
        mode: RetrievalMode = RetrievalMode.HYBRID,
        overrides: dict[str, object] | None = None,
    ) -> RetrievalResult:
        r = self._settings.retrieval
        overrides = overrides or {}
        profile_id = self.embedding_profile_id
        degraded: dict[str, bool] = {}
        timings: dict[str, float] = {}

        if kb_active_profile is not None and kb_active_profile != profile_id:
            raise ConflictError(
                f"knowledge base was indexed with embedding profile {kb_active_profile}, "
                f"but the service is configured for {profile_id}; run reindex or restore config"
            )

        collection = qdrant_collection_name(str(knowledge_base_id), profile_id)
        store = QdrantVectorStore(self._settings)
        try:
            kb_empty = not await store.collection_exists(collection) or (
                await store.count(collection) == 0
            )
            if kb_empty:
                return RetrievalResult(
                    search_query=search_query,
                    mode=mode,
                    candidates=[],
                    abstention=decide(
                        [],
                        kb_is_empty=True,
                        abstain_on_empty=r.abstain_on_empty,
                        reranker_model=self._reranker.model_id if self._reranker else None,
                        abstain_min_results=r.abstain_min_results,
                        abstain_fusion_floor=r.abstain_fusion_floor,
                        low_confidence_margin=r.low_confidence_margin,
                    ),
                    fusion_strategy=r.fusion_strategy.value,
                    embedding_profile_id=profile_id,
                    degraded=degraded,
                )

            rf = RetrievalFilter(knowledge_base_id=str(knowledge_base_id))
            dense_hits: list[Ranked] = []
            sparse_hits: list[Ranked] = []

            if mode in (RetrievalMode.DENSE, RetrievalMode.HYBRID):
                t = time.perf_counter()
                qvec = await self._embedder.embed_query(search_query)
                timings["embed"] = _ms(t)
                t = time.perf_counter()
                raw = await store.search_dense(
                    collection, qvec, limit=r.dense_top_k, rf=rf, with_vectors=True
                )
                timings["dense"] = _ms(t)
                dense_hits = [Ranked(h.point_id, h.score) for h in raw]
                dense_vectors = {h.point_id: h.dense for h in raw if h.dense}
            else:
                dense_vectors = {}

            if mode in (RetrievalMode.SPARSE, RetrievalMode.HYBRID) and r.hybrid_enabled:
                try:
                    from app.providers.sparse import get_sparse_encoder

                    t = time.perf_counter()
                    sv = await get_sparse_encoder().encode_query(search_query)
                    raw_s = await store.search_sparse(
                        collection, sv.indices, sv.values, limit=r.sparse_top_k, rf=rf
                    )
                    timings["sparse"] = _ms(t)
                    sparse_hits = [Ranked(h.point_id, h.score) for h in raw_s]
                except Exception as exc:
                    _log.warning("retrieval.sparse_failed", error=str(exc))
                    degraded["sparse"] = True

            t = time.perf_counter()
            if mode is RetrievalMode.DENSE or not sparse_hits:
                fused = dense_hits[: r.fusion_top_k]
            elif mode is RetrievalMode.SPARSE:
                fused = sparse_hits[: r.fusion_top_k]
            else:
                fused = fuse(
                    dense_hits,
                    sparse_hits,
                    strategy=r.fusion_strategy,
                    rrf_k=r.rrf_k,
                    dense_weight=r.hybrid_dense_weight,
                    sparse_weight=r.hybrid_sparse_weight,
                    limit=r.fusion_top_k,
                )
            timings["fuse"] = _ms(t)

            # hydrate content from Postgres
            ids = [uuid.UUID(x.id) for x in fused]
            async with session_scope(self._settings) as session:
                rows = await ChunkRepository(session).get_many(ids)
                doc_ids = {c.document_id for c in rows.values()}
                from sqlalchemy import select as _select

                from app.infra.db.models import Document as _Doc

                docs = {
                    d.id: d
                    for d in (
                        await session.execute(_select(_Doc).where(_Doc.id.in_(doc_ids)))
                    ).scalars()
                }
            candidates: list[ScoredChunk] = []
            for ranked in fused:
                chunk = rows.get(uuid.UUID(ranked.id))
                if chunk is None:
                    continue
                candidates.append(
                    ScoredChunk(
                        chunk_id=ranked.id,
                        document_id=str(chunk.document_id),
                        score=ranked.score,
                        content=chunk.content,
                        filename=(
                            docs[chunk.document_id].filename if chunk.document_id in docs else ""
                        ),
                        page_no=chunk.page_no,
                        ordinal=chunk.ordinal,
                        dense=tuple(dense_vectors.get(ranked.id, ())) or None,
                        section_path=tuple(chunk.section_path),
                    )
                )

            t = time.perf_counter()
            candidates = suppress_duplicates(candidates, cosine_threshold=r.dedup_cosine)
            timings["dedup"] = _ms(t)

            reranked_debug: list[dict[str, object]] = []
            if self._reranker is not None and candidates:
                t = time.perf_counter()
                try:
                    top = candidates[: r.rerank_input_k]
                    rr = await asyncio.wait_for(
                        self._reranker.rerank(
                            search_query,
                            [RerankCandidate(id=c.chunk_id, text=c.content) for c in top],
                            top_n=r.rerank_output_k,
                        ),
                        timeout=r.rerank_timeout_ms / 1000,
                    )
                    by_id = {c.chunk_id: c for c in candidates}
                    candidates = [
                        _rescore(by_id[res.id], res.score) for res in rr if res.id in by_id
                    ]
                    reranked_debug = [{"id": res.id, "score": res.score} for res in rr]
                except Exception as exc:
                    _log.warning("retrieval.rerank_degraded", error=str(exc))
                    degraded["rerank"] = True
                    candidates = candidates[: r.rerank_output_k]
                timings["rerank"] = _ms(t)
            else:
                candidates = candidates[: r.rerank_output_k]

            abstention = decide(
                candidates,
                kb_is_empty=False,
                abstain_on_empty=r.abstain_on_empty,
                reranker_model=self._reranker.model_id
                if (self._reranker and not degraded.get("rerank"))
                else None,
                abstain_min_results=r.abstain_min_results,
                abstain_fusion_floor=r.abstain_fusion_floor,
                low_confidence_margin=r.low_confidence_margin,
            )

            record_retrieval_timings(timings)
            for _component, _on in degraded.items():
                if _on:
                    DEGRADED.labels(component=_component).inc()

            return RetrievalResult(
                search_query=search_query,
                mode=mode,
                candidates=candidates,
                abstention=abstention,
                fusion_strategy=r.fusion_strategy.value,
                embedding_profile_id=profile_id,
                degraded=degraded,
                latency_ms=timings,
                dense_hits=[{"id": h.id, "score": h.score} for h in dense_hits[:50]],
                sparse_hits=[{"id": h.id, "score": h.score} for h in sparse_hits[:50]],
                fused=[{"id": h.id, "score": h.score} for h in fused[:50]],
                reranked=reranked_debug,
            )
        finally:
            await store.close()


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def _rescore(chunk: ScoredChunk, score: float) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        score=score,
        content=chunk.content,
        filename=chunk.filename,
        page_no=chunk.page_no,
        ordinal=chunk.ordinal,
        dense=chunk.dense,
        section_path=chunk.section_path,
    )
