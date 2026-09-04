"""Document DTOs (docs/ARCHITECTURE.md §23.1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.core.enums import DocumentStatus
from app.infra.db.models import Document


class DocumentResponse(BaseModel):
    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    filename: str
    mime: str
    size_bytes: int
    page_count: int | None
    lang: str | None
    language_warning: bool
    status: DocumentStatus
    failed_stage: str | None
    failure_reason: str | None
    active_index_version: int | None
    content_hash: str
    created_at: datetime
    indexed_at: datetime | None

    @classmethod
    def from_model(cls, doc: Document) -> DocumentResponse:
        return cls(
            id=doc.id,
            knowledge_base_id=doc.knowledge_base_id,
            filename=doc.filename,
            mime=doc.mime,
            size_bytes=doc.size_bytes,
            page_count=doc.page_count,
            lang=doc.lang,
            language_warning=doc.language_warning,
            status=doc.status,
            failed_stage=doc.failed_stage,
            failure_reason=doc.failure_reason,
            active_index_version=doc.active_index_version,
            content_hash=doc.content_hash,
            created_at=doc.created_at,
            indexed_at=doc.indexed_at,
        )
