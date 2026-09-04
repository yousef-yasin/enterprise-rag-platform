"""Document ingestion: upload + the PG<->Qdrant write protocol (docs/ARCHITECTURE.md §8, §9)."""

from __future__ import annotations

import contextlib
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.chunking import StructureAwareChunker
from app.core.embedding_profile import (
    ChunkPolicy,
    compute_embedding_profile_id,
    qdrant_collection_name,
)
from app.core.enums import (
    AuditAction,
    DocumentStatus,
    IngestionJobStatus,
)
from app.core.errors import (
    ConflictError,
    IngestionError,
    PayloadTooLargeError,
    UnprocessableDocumentError,
    ValidationError,
)
from app.core.hashing import content_sha256
from app.core.interfaces.embeddings import EmbeddingProvider
from app.core.models import ChunkSpec
from app.core.parsing import SUPPORTED_EXTENSIONS, ParseLimits, parse_document
from app.core.principal import Principal
from app.infra.db.models import Document, KnowledgeBase
from app.infra.db.repositories.audit import AuditRepository
from app.infra.db.repositories.documents import (
    ChunkRepository,
    DocumentRepository,
    IngestionJobRepository,
)
from app.infra.db.session import session_scope
from app.infra.qdrant.bootstrap import ensure_collection
from app.infra.qdrant.store import QdrantPoint, QdrantVectorStore
from app.infra.redis import jobstream
from app.infra.redis.client import get_redis
from app.obs.metrics import INGESTION_FAILURES, INGESTION_STAGE_SECONDS
from app.providers.registry import build_embedding_provider

_log = structlog.get_logger("app.ingestion")

_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


@dataclass(frozen=True, slots=True)
class UploadResult:
    document: Document
    created: bool


class IngestionService:
    """HTTP-side: validate, dedupe, persist, enqueue."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._docs = DocumentRepository(session)
        self._jobs = IngestionJobRepository(session)
        self._audit = AuditRepository(session)

    def _validate(self, filename: str, data: bytes) -> str:
        lower = filename.lower()
        ext = lower[lower.rfind(".") :] if "." in lower else ""
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValidationError(f"unsupported file type: {ext or filename!r}")
        if len(data) < self._settings.min_file_bytes:
            raise ValidationError("file is empty or too small")
        if len(data) > self._settings.max_upload_mb * 1024 * 1024:
            raise PayloadTooLargeError(
                f"file exceeds the {self._settings.max_upload_mb} MB upload limit"
            )
        return ext

    async def upload(
        self,
        kb: KnowledgeBase,
        principal: Principal,
        *,
        filename: str,
        data: bytes,
        request_id: str | None,
    ) -> UploadResult:
        ext = self._validate(filename, data)
        digest = content_sha256(data)

        existing = await self._docs.find_by_hash(kb.id, digest)
        if existing is not None:
            return UploadResult(document=existing, created=False)

        from app.infra.storage import build_object_storage

        storage = build_object_storage(self._settings)
        storage_key = uuid.uuid4().hex
        await storage.put(
            storage_key, data, content_type=_MIME.get(ext, "application/octet-stream")
        )

        doc = self._docs.add(
            kb_id=kb.id,
            filename=filename[:512],
            content_hash=digest,
            mime=_MIME.get(ext, "application/octet-stream"),
            size_bytes=len(data),
            storage_key=storage_key,
        )
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            winner = await self._docs.find_by_hash(kb.id, digest)
            if winner is None:
                raise ConflictError("concurrent upload conflict") from None
            return UploadResult(document=winner, created=False)

        self._jobs.add(doc.id)
        self._audit.record(
            actor_type=principal.actor_type,
            actor_id=principal.user_id,
            action=AuditAction.DOCUMENT_UPLOAD,
            target_type="document",
            target_id=doc.id,
            knowledge_base_id=kb.id,
            meta={"filename": filename, "size_bytes": len(data)},
            request_id=request_id,
        )
        await self._session.flush()

        from app.workers import queue

        await queue.enqueue(self._settings, "ingest_document", str(doc.id))
        return UploadResult(document=doc, created=True)

    async def reprocess(
        self, doc: Document, principal: Principal, *, request_id: str | None
    ) -> None:
        doc.next_index_version = (doc.active_index_version or 0) + 1
        doc.status = DocumentStatus.PENDING
        doc.failed_stage = None
        doc.failure_reason = None
        self._jobs.add(doc.id)
        self._audit.record(
            actor_type=principal.actor_type,
            actor_id=principal.user_id,
            action=AuditAction.DOCUMENT_REPROCESS,
            target_type="document",
            target_id=doc.id,
            knowledge_base_id=doc.knowledge_base_id,
            meta={"target_version": doc.next_index_version},
            request_id=request_id,
        )
        await self._session.flush()
        from app.workers import queue

        await queue.enqueue(self._settings, "reprocess_document", str(doc.id))

    async def soft_delete(
        self, doc: Document, principal: Principal, *, request_id: str | None
    ) -> None:
        doc.deleted_at = datetime.now(UTC)
        self._audit.record(
            actor_type=principal.actor_type,
            actor_id=principal.user_id,
            action=AuditAction.DOCUMENT_DELETE,
            target_type="document",
            target_id=doc.id,
            knowledge_base_id=doc.knowledge_base_id,
            request_id=request_id,
        )
        await self._session.flush()
        from app.workers import queue

        await queue.enqueue(self._settings, "purge_document", str(doc.id))


class IngestionPipeline:
    """Worker-side: the §9.2 write protocol for one document/version."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _parse_limits(self) -> ParseLimits:
        s = self._settings
        return ParseLimits(
            max_pages=s.max_pages,
            max_chunks_per_doc=s.max_chunks_per_doc,
            min_text_chars_per_page=s.min_text_chars_per_page,
            min_doc_chars=s.min_doc_chars,
            archive_max_uncompressed_bytes=s.archive_max_uncompressed_mb * 1024 * 1024,
            archive_max_entries=s.archive_max_entries,
            archive_max_ratio=s.archive_max_ratio,
        )

    async def run(self, document_id: str) -> str:
        settings = self._settings
        _t_start = time.perf_counter()
        doc_uuid = uuid.UUID(document_id)
        embedder = build_embedding_provider(settings)
        store = QdrantVectorStore(settings)
        redis = get_redis(settings)

        try:
            async with session_scope(settings) as session:
                locked = await _try_lock(session, doc_uuid)
                if not locked:
                    return "locked"
                doc = await DocumentRepository(session).get(doc_uuid)
                if doc is None or doc.deleted_at is not None:
                    return "gone"
                job = await IngestionJobRepository(session).latest_for_document(doc_uuid)
                target_version = doc.next_index_version
                doc.status = DocumentStatus.PROCESSING
                if job is not None:
                    job.status = IngestionJobStatus.RUNNING
                    job.started_at = datetime.now(UTC)
                    job.attempts += 1
                await session.flush()

            await self._emit(redis, document_id, "processing", stage="parse")

            from app.infra.storage import build_object_storage

            data = await build_object_storage(settings).get(doc.storage_key)

            try:
                tree = parse_document(data, filename=doc.filename, limits=self._parse_limits())
            except (UnprocessableDocumentError, IngestionError):
                raise
            except Exception as exc:
                raise IngestionError(str(exc)[:200], stage="parse") from exc

            policy = ChunkPolicy.from_settings(settings)
            chunker = StructureAwareChunker(
                profile=embedder.profile, policy=policy, count_tokens=embedder.count_tokens
            )
            specs = chunker.chunk(tree)
            if not specs:
                raise UnprocessableDocumentError("no chunks produced", reason="no_text")
            if len(specs) > settings.max_chunks_per_doc:
                raise UnprocessableDocumentError(
                    f"document produces {len(specs)} chunks (limit {settings.max_chunks_per_doc})",
                    reason="too_large",
                )
            for spec in specs:
                if embedder.count_tokens(spec.embedding_input) > embedder.profile.max_tokens:
                    raise IngestionError("chunk exceeds embedding token limit", stage="chunk")

            _t_parse = time.perf_counter()
            INGESTION_STAGE_SECONDS.labels(stage="parse").observe(max(_t_parse - _t_start, 0.0))

            await self._emit(redis, document_id, "processing", stage="embed")
            dense_vectors, embed_ok = await self._embed(embedder, specs)
            sparse_vectors = await self._encode_sparse(specs)
            INGESTION_STAGE_SECONDS.labels(stage="embed").observe(
                max(time.perf_counter() - _t_parse, 0.0)
            )
            _t_index = time.perf_counter()

            profile_id = compute_embedding_profile_id(embedder.profile, policy)
            collection = qdrant_collection_name(str(doc.knowledge_base_id), profile_id)

            # ── PG txn A: chunk rows in `indexing` state ──────────────────────
            async with session_scope(settings) as session:
                await _try_lock(session, doc_uuid)
                chunk_repo = ChunkRepository(session)
                await chunk_repo.delete_document_version(doc_uuid, target_version)
                rows = chunk_repo.add_specs(
                    document_id=doc_uuid,
                    kb_id=doc.knowledge_base_id,
                    version=target_version,
                    specs=specs,
                    embedding_ok=embed_ok,
                )
                await session.flush()
                point_ids = [str(r.id) for r in rows]

            # ── Qdrant upsert ────────────────────────────────────────────────
            await self._emit(redis, document_id, "processing", stage="index")
            async with session_scope(settings) as session:
                await ensure_collection(
                    session, store, name=collection, dense_dim=embedder.profile.dimension
                )
            await self._upsert(
                store,
                collection,
                doc,
                specs,
                dense_vectors,
                embed_ok,
                point_ids,
                target_version,
                tree.lang,
                sparse_vectors,
            )

            # ── PG txn B: mark ready ─────────────────────────────────────────
            async with session_scope(settings) as session:
                await _try_lock(session, doc_uuid)
                fresh = await DocumentRepository(session).get(doc_uuid)
                assert fresh is not None
                chunk_repo = ChunkRepository(session)
                await chunk_repo.mark_version_ready(doc_uuid, target_version)
                any_failed = not all(embed_ok)
                fresh.status = (
                    DocumentStatus.PARTIALLY_INDEXED if any_failed else DocumentStatus.READY
                )
                previous = fresh.active_index_version
                fresh.active_index_version = target_version
                fresh.next_index_version = target_version + 1
                fresh.page_count = tree.page_count
                fresh.lang = tree.lang
                fresh.language_warning = bool(
                    tree.lang and tree.lang not in embedder.profile.supported_langs
                )
                kb = await session.get(KnowledgeBase, fresh.knowledge_base_id)
                if kb is not None and kb.active_embedding_profile_id is None:
                    kb.active_embedding_profile_id = profile_id
                    kb.active_qdrant_collection = collection
                job2 = await IngestionJobRepository(session).latest_for_document(doc_uuid)
                if job2 is not None:
                    job2.status = IngestionJobStatus.SUCCEEDED
                    job2.finished_at = datetime.now(UTC)
                    job2.last_stage = "finalize"
                await session.flush()

            if previous is not None and previous != target_version:
                from app.workers import queue

                await queue.enqueue(settings, "delete_stale_points", document_id, target_version)

            INGESTION_STAGE_SECONDS.labels(stage="index").observe(
                max(time.perf_counter() - _t_index, 0.0)
            )
            INGESTION_STAGE_SECONDS.labels(stage="total").observe(
                max(time.perf_counter() - _t_start, 0.0)
            )
            await self._emit(
                redis, document_id, fresh.status.value, stage="finalize", chunks=len(specs)
            )
            return fresh.status.value

        except UnprocessableDocumentError as exc:
            await self._fail(
                settings,
                doc_uuid,
                redis,
                stage=str(exc.details.get("stage", "parse")),
                reason=exc.reason,
                message=exc.message,
                terminal=True,
            )
            return "failed"
        except IngestionError as exc:
            await self._fail(
                settings,
                doc_uuid,
                redis,
                stage=exc.stage,
                reason="parse_error",
                message=exc.message,
                terminal=False,
            )
            raise
        except Exception as exc:
            _log.exception("ingest.error", document_id=document_id)
            await self._fail(
                settings,
                doc_uuid,
                redis,
                stage="index",
                reason="parse_error",
                message=str(exc)[:200],
                terminal=False,
            )
            raise
        finally:
            await store.close()

    # ── stage helpers ────────────────────────────────────────────────────────
    async def _encode_sparse(
        self, specs: list[ChunkSpec]
    ) -> list[tuple[list[int], list[float]] | None]:
        if not self._settings.retrieval.hybrid_enabled:
            return [None] * len(specs)
        try:
            from app.providers.sparse import get_sparse_encoder

            encoded = await get_sparse_encoder().encode_documents([s.content for s in specs])
            return [(sv.indices, sv.values) for sv in encoded]
        except Exception as exc:
            _log.warning("ingest.sparse_unavailable", error=str(exc))
            return [None] * len(specs)

    async def _embed(
        self, embedder: EmbeddingProvider, specs: list[ChunkSpec]
    ) -> tuple[list[list[float] | None], list[bool]]:
        vectors: list[list[float] | None] = []
        ok: list[bool] = []
        batch = embedder.max_batch
        for start in range(0, len(specs), batch):
            group = [s.embedding_input for s in specs[start : start + batch]]
            try:
                embedded = await embedder.embed_documents(group)
                vectors.extend(embedded)
                ok.extend([True] * len(embedded))
            except Exception:
                _log.warning("embed.batch_failed", start=start)
                vectors.extend([None] * len(group))
                ok.extend([False] * len(group))
        return vectors, ok

    async def _upsert(
        self,
        store: QdrantVectorStore,
        collection: str,
        doc: Document,
        specs: list[ChunkSpec],
        dense_vectors: list[list[float] | None],
        embed_ok: list[bool],
        point_ids: list[str],
        version: int,
        lang: str | None,
        sparse_vectors: list[tuple[list[int], list[float]] | None],
    ) -> None:
        batch = self._settings.qdrant_upsert_batch
        points: list[QdrantPoint] = []
        for spec, vec, ok, pid, sparse in zip(
            specs, dense_vectors, embed_ok, point_ids, sparse_vectors, strict=True
        ):
            if not ok or vec is None:
                continue
            points.append(
                QdrantPoint(
                    point_id=pid,
                    dense=vec,
                    sparse_indices=sparse[0] if sparse else None,
                    sparse_values=sparse[1] if sparse else None,
                    payload={
                        "chunk_id": pid,
                        "document_id": str(doc.id),
                        "knowledge_base_id": str(doc.knowledge_base_id),
                        "doc_version": version,
                        "ordinal": spec.ordinal,
                        "page_no": spec.page_no,
                        "filename": doc.filename,
                        "lang": lang,
                        "snippet": spec.content[:300],
                    },
                )
            )
        for start in range(0, len(points), batch):
            last = start + batch >= len(points)
            await store.upsert(collection, points[start : start + batch], wait=last)

    async def _emit(self, redis: Redis, document_id: str, status: str, **extra: object) -> None:
        with contextlib.suppress(Exception):  # stream is best-effort
            await jobstream.publish(
                redis, document_id, {"status": status, "ts": datetime.now(UTC).isoformat(), **extra}
            )

    async def _fail(
        self,
        settings: Settings,
        doc_uuid: uuid.UUID,
        redis: Redis,
        *,
        stage: str,
        reason: str,
        message: str,
        terminal: bool,
    ) -> None:
        async with session_scope(settings) as session:
            doc = await DocumentRepository(session).get(doc_uuid)
            if doc is None:
                return
            job = await IngestionJobRepository(session).latest_for_document(doc_uuid)
            attempts = job.attempts if job else 0
            is_terminal = terminal or attempts >= settings.ingest_max_attempts
            if job is not None:
                job.failed_stage = stage
                job.error = message
                job.status = IngestionJobStatus.FAILED if is_terminal else IngestionJobStatus.QUEUED
                if is_terminal:
                    job.finished_at = datetime.now(UTC)
            if is_terminal:
                doc.status = DocumentStatus.FAILED
                doc.failed_stage = stage
                doc.failure_reason = reason
                INGESTION_FAILURES.labels(reason=reason or "unknown").inc()
            await session.flush()
        await self._emit(
            redis, str(doc_uuid), "failed" if terminal else "retrying", stage=stage, reason=reason
        )


async def _try_lock(session: AsyncSession, document_id: uuid.UUID) -> bool:
    row = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtext(:k))"),
        {"k": f"doc:{document_id}"},
    )
    return bool(row.scalar_one())
