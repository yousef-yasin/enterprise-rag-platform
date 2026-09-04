"""Qdrant vector store adapter (docs/ARCHITECTURE.md §9, §12, §20)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.config import Settings
from app.core.enums import FusionStrategy

_DENSE = "dense"
_SPARSE = "sparse"


@dataclass(slots=True)
class QdrantPoint:
    point_id: str
    dense: list[float]
    payload: dict[str, Any]
    sparse_indices: list[int] | None = None
    sparse_values: list[float] | None = None


@dataclass(slots=True)
class QdrantHit:
    point_id: str
    score: float
    payload: dict[str, Any]
    dense: list[float] | None = None


@dataclass(slots=True)
class RetrievalFilter:
    knowledge_base_id: str
    document_ids: list[str] | None = None
    doc_versions: dict[str, int] = field(default_factory=dict)  # document_id -> active version
    lang: str | None = None


class QdrantVectorStore:
    def __init__(self, settings: Settings) -> None:
        self._client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=(
                settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
            ),
            timeout=int(settings.qdrant_timeout_s),
            prefer_grpc=False,
            check_compatibility=False,
        )
        self._ef = settings.qdrant_search_ef
        self._on_disk = settings.qdrant_vectors_on_disk

    async def close(self) -> None:
        await self._client.close()

    async def collection_exists(self, name: str) -> bool:
        return bool(await self._client.collection_exists(name))

    async def ensure_collection(self, name: str, *, dense_dim: int) -> None:
        if await self._client.collection_exists(name):
            return
        await self._client.create_collection(
            collection_name=name,
            vectors_config={
                _DENSE: models.VectorParams(
                    size=dense_dim,
                    distance=models.Distance.COSINE,
                    on_disk=self._on_disk,
                    hnsw_config=models.HnswConfigDiff(m=16, ef_construct=128),
                )
            },
            sparse_vectors_config={
                _SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
            on_disk_payload=True,
        )
        for field_name, schema in (
            ("document_id", models.PayloadSchemaType.KEYWORD),
            ("knowledge_base_id", models.PayloadSchemaType.KEYWORD),
            ("doc_version", models.PayloadSchemaType.INTEGER),
            ("lang", models.PayloadSchemaType.KEYWORD),
        ):
            await self._client.create_payload_index(
                name, field_name=field_name, field_schema=schema
            )

    async def drop_collection(self, name: str) -> None:
        if await self._client.collection_exists(name):
            await self._client.delete_collection(name)

    async def upsert(self, collection: str, points: Sequence[QdrantPoint], *, wait: bool) -> None:
        if not points:
            return
        payload_points = []
        for p in points:
            vectors: dict[str, Any] = {_DENSE: p.dense}
            if p.sparse_indices is not None and p.sparse_values is not None:
                vectors[_SPARSE] = models.SparseVector(
                    indices=p.sparse_indices, values=p.sparse_values
                )
            payload_points.append(
                models.PointStruct(id=p.point_id, vector=vectors, payload=p.payload)
            )
        await self._client.upsert(collection, points=payload_points, wait=wait)

    async def delete_points(self, collection: str, point_ids: Sequence[str]) -> None:
        if not point_ids:
            return
        await self._client.delete(
            collection, points_selector=models.PointIdsList(points=list(point_ids)), wait=True
        )

    async def delete_by_document_version(
        self, collection: str, document_id: str, *, keep_version: int
    ) -> None:
        await self._client.delete(
            collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id", match=models.MatchValue(value=document_id)
                        )
                    ],
                    must_not=[
                        models.FieldCondition(
                            key="doc_version", match=models.MatchValue(value=keep_version)
                        )
                    ],
                )
            ),
            wait=True,
        )

    async def delete_by_document(self, collection: str, document_id: str) -> None:
        await self._client.delete(
            collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id", match=models.MatchValue(value=document_id)
                        )
                    ]
                )
            ),
            wait=True,
        )

    async def count(self, collection: str, *, knowledge_base_id: str | None = None) -> int:
        flt = None
        if knowledge_base_id is not None:
            flt = models.Filter(
                must=[
                    models.FieldCondition(
                        key="knowledge_base_id", match=models.MatchValue(value=knowledge_base_id)
                    )
                ]
            )
        result = await self._client.count(collection, count_filter=flt, exact=True)
        return int(result.count)

    async def scroll_ids(
        self, collection: str, *, document_id: str, limit: int = 1000
    ) -> list[tuple[str, int]]:
        points, _next = await self._client.scroll(
            collection,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id", match=models.MatchValue(value=document_id)
                    )
                ]
            ),
            limit=limit,
            with_payload=["doc_version"],
            with_vectors=False,
        )
        return [(str(p.id), int((p.payload or {}).get("doc_version", 0))) for p in points]

    # ── search ───────────────────────────────────────────────────────────────
    def _filter(self, rf: RetrievalFilter) -> models.Filter:
        must: list[models.Condition] = [
            models.FieldCondition(
                key="knowledge_base_id", match=models.MatchValue(value=rf.knowledge_base_id)
            )
        ]
        if rf.document_ids:
            must.append(
                models.FieldCondition(
                    key="document_id", match=models.MatchAny(any=list(rf.document_ids))
                )
            )
        if rf.lang:
            must.append(models.FieldCondition(key="lang", match=models.MatchValue(value=rf.lang)))
        should_version: list[models.Condition] = []
        for doc_id, version in rf.doc_versions.items():
            should_version.append(
                models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id", match=models.MatchValue(value=doc_id)
                        ),
                        models.FieldCondition(
                            key="doc_version", match=models.MatchValue(value=version)
                        ),
                    ]
                )
            )
        flt = models.Filter(must=must)
        if should_version:
            flt.must = [*must, models.Filter(should=should_version)]
        return flt

    async def search_dense(
        self,
        collection: str,
        vector: list[float],
        *,
        limit: int,
        rf: RetrievalFilter,
        with_vectors: bool = False,
    ) -> list[QdrantHit]:
        result = await self._client.query_points(
            collection,
            query=vector,
            using=_DENSE,
            limit=limit,
            query_filter=self._filter(rf),
            with_payload=True,
            with_vectors=[_DENSE] if with_vectors else False,
            search_params=models.SearchParams(hnsw_ef=self._ef),
        )
        return [self._to_hit(p, with_vectors) for p in result.points]

    async def search_sparse(
        self,
        collection: str,
        indices: list[int],
        values: list[float],
        *,
        limit: int,
        rf: RetrievalFilter,
    ) -> list[QdrantHit]:
        result = await self._client.query_points(
            collection,
            query=models.SparseVector(indices=indices, values=values),
            using=_SPARSE,
            limit=limit,
            query_filter=self._filter(rf),
            with_payload=True,
        )
        return [self._to_hit(p, False) for p in result.points]

    async def query_hybrid(
        self,
        collection: str,
        *,
        dense: list[float],
        sparse_indices: list[int],
        sparse_values: list[float],
        dense_limit: int,
        sparse_limit: int,
        limit: int,
        rf: RetrievalFilter,
        strategy: FusionStrategy,
    ) -> list[QdrantHit]:
        fusion = models.Fusion.DBSF if strategy is FusionStrategy.DBSF else models.Fusion.RRF
        flt = self._filter(rf)
        result = await self._client.query_points(
            collection,
            prefetch=[
                models.Prefetch(query=dense, using=_DENSE, limit=dense_limit, filter=flt),
                models.Prefetch(
                    query=models.SparseVector(indices=sparse_indices, values=sparse_values),
                    using=_SPARSE,
                    limit=sparse_limit,
                    filter=flt,
                ),
            ],
            query=models.FusionQuery(fusion=fusion),
            limit=limit,
            with_payload=True,
        )
        return [self._to_hit(p, False) for p in result.points]

    @staticmethod
    def _to_hit(point: Any, with_vectors: bool) -> QdrantHit:
        dense = None
        if with_vectors and point.vector:
            raw = point.vector.get(_DENSE) if isinstance(point.vector, dict) else point.vector
            dense = list(raw) if raw is not None else None
        return QdrantHit(
            point_id=str(point.id),
            score=float(point.score),
            payload=dict(point.payload or {}),
            dense=dense,
        )
