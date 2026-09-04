"""Document + chunk + ingestion-job persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ChunkStatus, DocumentStatus, EmbeddingStatus, IngestionJobStatus
from app.core.models import ChunkSpec
from app.infra.db.models import Chunk, Document, IngestionJob


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, document_id: uuid.UUID) -> Document | None:
        return await self._session.get(Document, document_id)

    async def get_active(self, document_id: uuid.UUID) -> Document | None:
        doc = await self._session.get(Document, document_id)
        if doc is None or doc.deleted_at is not None:
            return None
        return doc

    async def find_by_hash(self, kb_id: uuid.UUID, content_hash: str) -> Document | None:
        result = await self._session.execute(
            select(Document).where(
                Document.knowledge_base_id == kb_id,
                Document.content_hash == content_hash,
                Document.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_kb(
        self,
        kb_id: uuid.UUID,
        *,
        status: DocumentStatus | None,
        limit: int,
        offset: int,
    ) -> list[Document]:
        stmt = (
            select(Document)
            .where(Document.knowledge_base_id == kb_id, Document.deleted_at.is_(None))
            .order_by(Document.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(Document.status == status)
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def add(
        self,
        *,
        kb_id: uuid.UUID,
        filename: str,
        content_hash: str,
        mime: str,
        size_bytes: int,
        storage_key: str,
    ) -> Document:
        doc = Document(
            knowledge_base_id=kb_id,
            filename=filename,
            content_hash=content_hash,
            mime=mime,
            size_bytes=size_bytes,
            storage_key=storage_key,
            status=DocumentStatus.PENDING,
            next_index_version=1,
        )
        self._session.add(doc)
        return doc

    async def list_stale(self, older_than_seconds: int, limit: int) -> list[Document]:
        cutoff = datetime.now(UTC).timestamp() - older_than_seconds
        result = await self._session.execute(
            select(Document)
            .where(
                Document.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING]),
                Document.deleted_at.is_(None),
                func.extract("epoch", Document.updated_at) < cutoff,
            )
            .limit(limit)
        )
        return list(result.scalars().all())


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def delete_document_version(self, document_id: uuid.UUID, version: int) -> None:
        await self._session.execute(
            delete(Chunk).where(Chunk.document_id == document_id, Chunk.index_version == version)
        )

    async def delete_stale_versions(self, document_id: uuid.UUID, keep_version: int) -> None:
        await self._session.execute(
            delete(Chunk).where(
                Chunk.document_id == document_id, Chunk.index_version != keep_version
            )
        )

    async def orphan_ready_chunks(self, limit: int) -> list[Chunk]:
        """Ready chunks whose version is no longer the document's active version."""
        result = await self._session.execute(
            select(Chunk)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.status == ChunkStatus.READY,
                Document.active_index_version.is_not(None),
                Chunk.index_version != Document.active_index_version,
                Document.deleted_at.is_(None),
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    def add_specs(
        self,
        *,
        document_id: uuid.UUID,
        kb_id: uuid.UUID,
        version: int,
        specs: list[ChunkSpec],
        embedding_ok: list[bool],
    ) -> list[Chunk]:
        rows: list[Chunk] = []
        now = datetime.now(UTC)
        for spec, ok in zip(specs, embedding_ok, strict=True):
            row = Chunk(
                id=uuid.uuid4(),
                document_id=document_id,
                knowledge_base_id=kb_id,
                index_version=version,
                ordinal=spec.ordinal,
                content=spec.content,
                embedding_input=spec.embedding_input,
                token_count=spec.token_count,
                page_no=spec.page_no,
                page_span_low=spec.page_span_low,
                page_span_high=spec.page_span_high,
                char_start=spec.char_start,
                char_end=spec.char_end,
                section_path=spec.section_path,
                status=ChunkStatus.INDEXING,
                embedding_status=(EmbeddingStatus.OK if ok else EmbeddingStatus.FAILED),
                created_at=now,
            )
            self._session.add(row)
            rows.append(row)
        return rows

    async def list_for_version(self, document_id: uuid.UUID, version: int) -> list[Chunk]:
        result = await self._session.execute(
            select(Chunk)
            .where(Chunk.document_id == document_id, Chunk.index_version == version)
            .order_by(Chunk.ordinal)
        )
        return list(result.scalars().all())

    async def list_ready_for_document(self, document_id: uuid.UUID) -> list[Chunk]:
        doc = await self._session.get(Document, document_id)
        if doc is None or doc.active_index_version is None:
            return []
        result = await self._session.execute(
            select(Chunk)
            .where(
                Chunk.document_id == document_id,
                Chunk.index_version == doc.active_index_version,
                Chunk.status == ChunkStatus.READY,
            )
            .order_by(Chunk.ordinal)
        )
        return list(result.scalars().all())

    async def get_many(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, Chunk]:
        if not ids:
            return {}
        result = await self._session.execute(select(Chunk).where(Chunk.id.in_(ids)))
        return {c.id: c for c in result.scalars().all()}

    async def mark_version_ready(self, document_id: uuid.UUID, version: int) -> None:
        chunks = await self.list_for_version(document_id, version)
        for chunk in chunks:
            if chunk.embedding_status is EmbeddingStatus.OK:
                chunk.status = ChunkStatus.READY

    async def count_ready(self, document_id: uuid.UUID, version: int) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Chunk)
            .where(
                Chunk.document_id == document_id,
                Chunk.index_version == version,
                Chunk.status == ChunkStatus.READY,
            )
        )
        return int(result.scalar_one())


class IngestionJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, document_id: uuid.UUID) -> IngestionJob:
        job = IngestionJob(
            document_id=document_id,
            status=IngestionJobStatus.QUEUED,
            attempts=0,
            created_at=datetime.now(UTC),
        )
        self._session.add(job)
        return job

    async def latest_for_document(self, document_id: uuid.UUID) -> IngestionJob | None:
        result = await self._session.execute(
            select(IngestionJob)
            .where(IngestionJob.document_id == document_id)
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_stale(self, older_than_seconds: int, limit: int) -> list[IngestionJob]:
        cutoff = datetime.now(UTC).timestamp() - older_than_seconds
        result = await self._session.execute(
            select(IngestionJob)
            .where(
                IngestionJob.status.in_([IngestionJobStatus.QUEUED, IngestionJobStatus.RUNNING]),
                func.coalesce(
                    func.extract("epoch", IngestionJob.started_at),
                    func.extract("epoch", IngestionJob.created_at),
                )
                < cutoff,
            )
            .limit(limit)
        )
        return list(result.scalars().all())
