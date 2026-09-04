"""API key DTOs (docs/ARCHITECTURE.md §25.3)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import ApiKeyScope
from app.infra.db.models import ApiKey


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[ApiKeyScope] = Field(min_length=1)
    knowledge_base_id: uuid.UUID | None = None


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: list[str]
    knowledge_base_id: uuid.UUID | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    @classmethod
    def from_model(cls, key: ApiKey) -> ApiKeyResponse:
        return cls(
            id=key.id,
            name=key.name,
            key_prefix=key.key_prefix,
            scopes=list(key.scopes),
            knowledge_base_id=key.knowledge_base_id,
            last_used_at=key.last_used_at,
            revoked_at=key.revoked_at,
            created_at=key.created_at,
        )


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned once on creation — includes the plaintext token."""

    token: str
