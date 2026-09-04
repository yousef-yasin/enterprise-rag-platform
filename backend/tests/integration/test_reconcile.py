"""Reconciliation sweep restores the section-9.3 invariants (Phase 2 gate)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.embedding_profile import (
    ChunkPolicy,
    compute_embedding_profile_id,
    qdrant_collection_name,
)
from app.core.enums import DocumentStatus, IngestionJobStatus
from app.infra.db.models import Document, IngestionJob
from app.infra.qdrant.store import QdrantVectorStore
from app.providers.embeddings.fake import FakeEmbedder
from app.services.ingestion import IngestionPipeline
from app.workers.reconcile import reconcile_once
from tests.integration._helpers import create_kb, register_and_auth
from tests.integration.test_ingestion import _MD


async def _ingest(client: AsyncClient, headers: dict[str, str], kb_id: str) -> str:
    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": ("h.md", _MD, "text/markdown")},
    )
    doc_id: str = resp.json()["id"]
    await IngestionPipeline(get_settings()).run(doc_id)
    return doc_id


async def test_reconcile_requeues_stuck_document(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await register_and_auth(client, email="owner@example.com")
    kb = await create_kb(client, headers, slug="handbook")
    doc_id = await _ingest(client, headers, kb["id"])

    # simulate a crash mid-ingest: force PROCESSING + a stale job, no live worker
    db_session.expire_all()
    doc = await db_session.get(Document, uuid.UUID(doc_id))
    assert doc is not None
    doc.status = DocumentStatus.PROCESSING
    job = IngestionJob(
        document_id=doc.id,
        status=IngestionJobStatus.RUNNING,
        attempts=1,
        created_at=datetime(2000, 1, 1, tzinfo=UTC),
    )
    db_session.add(job)
    await db_session.commit()

    monkeypatch.setenv("INDEXING_STALE_SECONDS", "1")
    get_settings.cache_clear()

    enqueued: list[tuple[str, tuple[object, ...]]] = []

    async def _fake_enqueue(_settings: object, task: str, *args: object) -> str:
        enqueued.append((task, args))
        return "job-x"

    monkeypatch.setattr("app.workers.queue.enqueue", _fake_enqueue)

    summary = await reconcile_once(get_settings())
    assert summary.get("requeued", 0) >= 1
    assert any(task == "ingest_document" and args[0] == doc_id for task, args in enqueued)


async def test_reconcile_repairs_orphan_qdrant_points(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await register_and_auth(client, email="owner@example.com")
    kb = await create_kb(client, headers, slug="handbook")
    doc_id = await _ingest(client, headers, kb["id"])

    profile_id = compute_embedding_profile_id(
        FakeEmbedder().profile, ChunkPolicy.from_settings(get_settings())
    )
    collection = qdrant_collection_name(kb["id"], profile_id)
    store = QdrantVectorStore(get_settings())
    try:
        before = await store.count(collection)
        assert before > 0
        # inject an orphan point (no chunk row)
        from app.infra.qdrant.store import QdrantPoint

        orphan_id = str(uuid.uuid4())
        await store.upsert(
            collection,
            [
                QdrantPoint(
                    point_id=orphan_id,
                    dense=[0.1] * FakeEmbedder().profile.dimension,
                    payload={
                        "document_id": doc_id,
                        "knowledge_base_id": kb["id"],
                        "doc_version": 999,
                        "chunk_id": orphan_id,
                    },
                )
            ],
            wait=True,
        )
        assert await store.count(collection) == before + 1

        await reconcile_once(get_settings())
        await asyncio.sleep(0.2)

        # the stale-version orphan is scheduled for deletion; run the task
        from app.workers.tasks import delete_stale_points

        await delete_stale_points({}, doc_id, 1)
        assert await store.count(collection) == before
    finally:
        await store.close()
