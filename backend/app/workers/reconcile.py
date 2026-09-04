"""Reconciliation sweep — enforces the section-9.3 consistency invariants.

Bounded work per run. Runs as an arq cron (every ``RECONCILE_INTERVAL_S``) and via
``rag reconcile``.
"""

from __future__ import annotations

import uuid
from collections import Counter

import structlog
from sqlalchemy import select

from app.config import Settings
from app.core.embedding_profile import (
    ChunkPolicy,
    compute_embedding_profile_id,
    qdrant_collection_name,
)
from app.core.enums import ChunkStatus, DocumentStatus, EmbeddingStatus
from app.infra.db.models import Chunk, Document, KnowledgeBase
from app.infra.db.repositories.documents import DocumentRepository, IngestionJobRepository
from app.infra.db.session import session_scope
from app.infra.qdrant.store import QdrantVectorStore
from app.providers.registry import build_embedding_provider

_log = structlog.get_logger("app.reconcile")


async def reconcile_once(settings: Settings) -> dict[str, int]:
    repairs: Counter[str] = Counter()
    batch = settings.reconcile_batch
    store = QdrantVectorStore(settings)
    try:
        embedder = build_embedding_provider(settings)
        profile_id = compute_embedding_profile_id(
            embedder.profile, ChunkPolicy.from_settings(settings)
        )

        # 1. stuck jobs / documents (INV-5) -> re-enqueue
        async with session_scope(settings) as session:
            stale_docs = await DocumentRepository(session).list_stale(
                settings.indexing_stale_seconds, batch
            )
            stale_jobs = await IngestionJobRepository(session).list_stale(
                settings.indexing_stale_seconds, batch
            )
        doc_ids = {str(d.id) for d in stale_docs} | {str(j.document_id) for j in stale_jobs}
        for doc_id in doc_ids:
            from app.workers import queue

            await queue.enqueue(settings, "ingest_document", doc_id)
            repairs["requeued"] += 1

        # 2/3. per-KB point<->chunk reconciliation (INV-1, INV-2, INV-4)
        async with session_scope(settings) as session:
            kbs = (await session.execute(select(KnowledgeBase).limit(batch))).scalars().all()
        for kb in kbs:
            collection = qdrant_collection_name(str(kb.id), profile_id)
            if not await store.collection_exists(collection):
                continue
            await _reconcile_collection(settings, store, str(kb.id), collection, repairs, batch)

        return dict(repairs)
    finally:
        await store.close()


async def _reconcile_collection(
    settings: Settings,
    store: QdrantVectorStore,
    kb_id: str,
    collection: str,
    repairs: Counter[str],
    batch: int,
) -> None:
    async with session_scope(settings) as session:
        docs = (
            (
                await session.execute(
                    select(Document).where(
                        Document.knowledge_base_id == uuid.UUID(kb_id),
                        Document.deleted_at.is_(None),
                        Document.active_index_version.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        active_by_doc: dict[str, int] = {
            str(d.id): d.active_index_version  # type: ignore[misc]
            for d in docs
        }
        chunk_rows = (
            await session.execute(
                select(Chunk.id, Chunk.document_id, Chunk.status).where(
                    Chunk.knowledge_base_id == uuid.UUID(kb_id)
                )
            )
        ).all()

    all_chunk_ids = {str(cid) for cid, _d, _s in chunk_rows}
    ready_by_doc: dict[str, set[str]] = {}
    for cid, doc_id, status in chunk_rows:
        if status is ChunkStatus.READY and str(doc_id) in active_by_doc:
            ready_by_doc.setdefault(str(doc_id), set()).add(str(cid))

    for doc_id, active_version in active_by_doc.items():
        points = await store.scroll_ids(collection, document_id=doc_id, limit=batch)
        point_ids = {pid for pid, _v in points}

        stale = [
            pid for pid, version in points if pid not in all_chunk_ids or version != active_version
        ]
        if stale:
            await store.delete_points(collection, stale)
            repairs["orphan_points"] += len(stale)

        missing = ready_by_doc.get(doc_id, set()) - point_ids
        if missing:
            repairs["orphan_chunks"] += len(missing)
            async with session_scope(settings) as session:
                for cid in missing:
                    chunk = await session.get(Chunk, uuid.UUID(cid))
                    if chunk is not None:
                        chunk.embedding_status = EmbeddingStatus.MISSING
                doc = await session.get(Document, uuid.UUID(doc_id))
                if doc is not None:
                    doc.status = DocumentStatus.PARTIALLY_INDEXED
            from app.workers import queue

            await queue.enqueue(settings, "reprocess_document", doc_id)
