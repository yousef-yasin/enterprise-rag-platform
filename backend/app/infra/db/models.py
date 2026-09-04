"""ORM models (docs/ARCHITECTURE.md §19).

One module for the whole schema; sections are added by the phase that introduces
them. Enums are stored as ``VARCHAR`` + ``CHECK`` (``native_enum=False``) so Alembic
downgrades are clean.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    ActorType,
    AuditAction,
    ChunkStatus,
    DocumentStatus,
    EmbeddingStatus,
    IngestionJobStatus,
    KBRole,
    MessageRole,
    ReindexJobStatus,
)
from app.infra.db.base import Base, TimestampMixin, uuid_pk


def _str_enum(enum_cls: type, name: str) -> Enum:
    return Enum(enum_cls, name=name, native_enum=False, length=32, validate_strings=True)


# ── Phase 1: identity, knowledge bases, access ────────────────────────────────
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(default=False, nullable=False)


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    active_embedding_profile_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    active_qdrant_collection: Mapped[str | None] = mapped_column(String(200), nullable=True)

    members: Mapped[list[KnowledgeBaseMember]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )


class KnowledgeBaseMember(Base):
    __tablename__ = "knowledge_base_members"

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[KBRole] = mapped_column(_str_enum(KBRole, "kb_role"), nullable=False)
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="members")


class ApiKey(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)
    knowledge_base_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_type: Mapped[ActorType] = mapped_column(
        _str_enum(ActorType, "actor_type"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    action: Mapped[AuditAction] = mapped_column(
        _str_enum(AuditAction, "audit_action"), nullable=False
    )
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    knowledge_base_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_audit_log_kb_created", "knowledge_base_id", "created_at"),)


# ── Phase 2: documents, chunks, ingestion ────────────────────────────────────
class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    language_warning: Mapped[bool] = mapped_column(default=False, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        _str_enum(DocumentStatus, "document_status"), nullable=False
    )
    failed_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(256), nullable=False)
    active_index_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_index_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "uq_documents_kb_hash_active",
            "knowledge_base_id",
            "content_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_documents_kb_status", "knowledge_base_id", "status"),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = uuid_pk()  # this id IS the Qdrant point id (§9.1)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    index_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    embedding_input: Mapped[str] = mapped_column(Text(), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_span_low: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_span_high: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    section_path: Mapped[list[str]] = mapped_column(ARRAY(Text()), default=list, nullable=False)
    status: Mapped[ChunkStatus] = mapped_column(
        _str_enum(ChunkStatus, "chunk_status"), nullable=False
    )
    embedding_status: Mapped[EmbeddingStatus] = mapped_column(
        _str_enum(EmbeddingStatus, "embedding_status"), nullable=False
    )
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_chunks_document_version", "document_id", "index_version"),
        Index("ix_chunks_kb", "knowledge_base_id"),
        Index("ix_chunks_document_status", "document_id", "status"),
        Index("ix_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[IngestionJobStatus] = mapped_column(
        _str_enum(IngestionJobStatus, "ingestion_job_status"), nullable=False
    )
    last_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failed_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    arq_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_ingestion_jobs_status", "status"),)


class ReindexJob(Base):
    __tablename__ = "reindex_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # kb_cutover
    target_embedding_profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[ReindexJobStatus] = mapped_column(
        _str_enum(ReindexJobStatus, "reindex_job_status"), nullable=False
    )
    total_docs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    done_docs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_docs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ── Phase 6-9: conversations, messages, citations, traces, feedback ──────────
class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = uuid_pk()
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    archived: Mapped[bool] = mapped_column(default=False, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, nullable=False)

    __table_args__ = (Index("ix_conversations_user", "user_id"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(
        _str_enum(MessageRole, "message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_query: Mapped[str | None] = mapped_column(Text(), nullable=True)
    search_query: Mapped[str | None] = mapped_column(Text(), nullable=True)
    was_rewritten: Mapped[bool] = mapped_column(default=False, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    latency_ms: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    abstained: Mapped[bool] = mapped_column(default=False, nullable=False)
    low_confidence: Mapped[bool] = mapped_column(default=False, nullable=False)
    degraded: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[uuid.UUID] = uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    citation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    score: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    was_cited: Mapped[bool] = mapped_column(default=False, nullable=False)
    weak: Mapped[bool] = mapped_column(default=False, nullable=False)
    chunk_content_snapshot: Mapped[str | None] = mapped_column(Text(), nullable=True)
    document_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (Index("ix_citations_message", "message_id"),)


class RetrievalTrace(Base):
    __tablename__ = "retrieval_traces"

    id: Mapped[uuid.UUID] = uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    raw_query: Mapped[str] = mapped_column(Text(), nullable=False)
    search_query: Mapped[str] = mapped_column(Text(), nullable=False)
    was_rewritten: Mapped[bool] = mapped_column(default=False, nullable=False)
    embedding_profile_id: Mapped[str] = mapped_column(String(32), nullable=False)
    fusion_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    dense_hits: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    sparse_hits: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    fused: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    reranked: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    context_chunk_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), default=list, nullable=False
    )
    cited_chunk_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), default=list, nullable=False
    )
    abstained: Mapped[bool] = mapped_column(default=False, nullable=False)
    low_confidence: Mapped[bool] = mapped_column(default=False, nullable=False)
    degraded: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    latency_ms: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_retrieval_traces_created", "created_at"),)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = uuid_pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[str] = mapped_column(String(8), nullable=False)  # up | down
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="one_rating_per_user"),
        CheckConstraint("rating in ('up','down')", name="rating_values"),
    )


# ── Phase 9: evaluation ─────────────────────────────────────────────────────
class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dataset_split: Mapped[str] = mapped_column(String(32), nullable=False)
    git_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    judge_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvalSample(Base):
    __tablename__ = "eval_samples"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text(), nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text(), nullable=True)
    relevant_chunk_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), default=list, nullable=False
    )
    relevant_doc_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), default=list, nullable=False
    )
    generated_answer: Mapped[str | None] = mapped_column(Text(), nullable=True)
    retrieved_chunk_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), default=list, nullable=False
    )
    cited_chunk_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), default=list, nullable=False
    )
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    latency_ms: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0, nullable=False)

    __table_args__ = (Index("ix_eval_samples_run", "run_id"),)
