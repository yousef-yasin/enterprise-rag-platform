"""Domain enumerations shared across layers (docs/ARCHITECTURE.md §19, §25)."""

from __future__ import annotations

from enum import StrEnum


class KBRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"

    @property
    def rank(self) -> int:
        return {KBRole.VIEWER: 1, KBRole.EDITOR: 2, KBRole.OWNER: 3}[self]

    def allows(self, required: KBRole) -> bool:
        return self.rank >= required.rank


class ApiKeyScope(StrEnum):
    KB_READ = "kb:read"
    KB_INGEST = "kb:ingest"
    KB_MANAGE = "kb:manage"
    CHAT = "chat"


class ActorType(StrEnum):
    USER = "user"
    API_KEY = "api_key"
    SYSTEM = "system"


class AuditAction(StrEnum):
    KB_CREATE = "kb.create"
    KB_DELETE = "kb.delete"
    KB_REINDEX = "kb.reindex"
    MEMBER_ADD = "member.add"
    MEMBER_REMOVE = "member.remove"
    DOCUMENT_UPLOAD = "document.upload"
    DOCUMENT_REPROCESS = "document.reprocess"
    DOCUMENT_DELETE = "document.delete"
    DOCUMENT_PURGE = "document.purge"
    APIKEY_CREATE = "apikey.create"
    APIKEY_REVOKE = "apikey.revoke"
    USER_CREATE = "user.create"
    AUTH_LOGIN_FAILED = "auth.login_failed"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    PARTIALLY_INDEXED = "partially_indexed"
    FAILED = "failed"


class IngestionJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReindexJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChunkStatus(StrEnum):
    INDEXING = "indexing"
    READY = "ready"


class EmbeddingStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    MISSING = "missing"


class RetrievalMode(StrEnum):
    DENSE = "dense"
    SPARSE = "sparse"
    HYBRID = "hybrid"


class FusionStrategy(StrEnum):
    RRF = "rrf"
    WEIGHTED_NORM = "weighted_norm"
    DBSF = "dbsf"


class DocumentFailureReason(StrEnum):
    ENCRYPTED = "encrypted"
    INSUFFICIENT_TEXT = "insufficient_text"
    NO_TEXT = "no_text"
    TOO_LARGE = "too_large"
    CORRUPT = "corrupt"
    ARCHIVE_LIMITS = "archive_limits"
    RESOURCE_LIMIT = "resource_limit"
    PARSE_ERROR = "parse_error"
    EMBEDDING_FAILED = "embedding_failed"
