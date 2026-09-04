"""arq task functions (docs/ARCHITECTURE.md §22)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from app.config import get_settings
from app.core.embedding_profile import compute_embedding_profile_id, qdrant_collection_name
from app.infra.db.repositories.documents import DocumentRepository
from app.infra.db.session import session_scope
from app.infra.qdrant.store import QdrantVectorStore
from app.providers.registry import build_embedding_provider
from app.services.ingestion import IngestionPipeline

_log = structlog.get_logger("app.workers.tasks")


async def ingest_document(_ctx: dict[str, Any], document_id: str) -> str:
    settings = get_settings()
    return await IngestionPipeline(settings).run(document_id)


async def reprocess_document(_ctx: dict[str, Any], document_id: str) -> str:
    settings = get_settings()
    return await IngestionPipeline(settings).run(document_id)


async def delete_stale_points(_ctx: dict[str, Any], document_id: str, keep_version: int) -> str:
    settings = get_settings()
    doc_uuid = uuid.UUID(document_id)
    store = QdrantVectorStore(settings)
    try:
        async with session_scope(settings) as session:
            doc = await DocumentRepository(session).get(doc_uuid)
            if doc is None:
                return "gone"
            embedder = build_embedding_provider(settings)
            from app.core.embedding_profile import ChunkPolicy

            profile_id = compute_embedding_profile_id(
                embedder.profile, ChunkPolicy.from_settings(settings)
            )
            collection = qdrant_collection_name(str(doc.knowledge_base_id), profile_id)
            from app.infra.db.repositories.documents import ChunkRepository

            await ChunkRepository(session).delete_stale_versions(doc_uuid, keep_version)
        await store.delete_by_document_version(collection, document_id, keep_version=keep_version)
        return "ok"
    finally:
        await store.close()


async def purge_document(_ctx: dict[str, Any], document_id: str) -> str:
    settings = get_settings()
    doc_uuid = uuid.UUID(document_id)
    store = QdrantVectorStore(settings)
    try:
        async with session_scope(settings) as session:
            doc = await DocumentRepository(session).get(doc_uuid)
            if doc is None:
                return "gone"
            embedder = build_embedding_provider(settings)
            from app.core.embedding_profile import ChunkPolicy

            profile_id = compute_embedding_profile_id(
                embedder.profile, ChunkPolicy.from_settings(settings)
            )
            collection = qdrant_collection_name(str(doc.knowledge_base_id), profile_id)
            from sqlalchemy import delete

            from app.infra.db.models import Chunk

            await session.execute(delete(Chunk).where(Chunk.document_id == doc_uuid))
        await store.delete_by_document(collection, document_id)
        return "ok"
    finally:
        await store.close()


async def reconcile_cron(_ctx: dict[str, Any]) -> str:
    from app.workers.reconcile import reconcile_once

    summary = await reconcile_once(get_settings())
    return str(summary)


async def trace_gc_cron(_ctx: dict[str, Any]) -> str:
    settings = get_settings()
    from sqlalchemy import delete

    from app.infra.db.models import RetrievalTrace

    cutoff = datetime.now(UTC).timestamp() - settings.trace_retention_days * 86400
    async with session_scope(settings) as session:
        from sqlalchemy import func

        result = await session.execute(
            delete(RetrievalTrace).where(func.extract("epoch", RetrievalTrace.created_at) < cutoff)
        )
    return f"deleted {getattr(result, 'rowcount', 0)}"


async def jobstream_reaper_cron(_ctx: dict[str, Any]) -> str:
    settings = get_settings()
    from app.infra.redis import jobstream
    from app.infra.redis.client import get_redis

    reaped = await jobstream.reap(get_redis(settings), settings.trace_retention_days)
    return f"reaped {reaped}"
