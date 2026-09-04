"""The authenticated caller (docs/ARCHITECTURE.md §25.3)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.enums import ActorType, ApiKeyScope


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    is_admin: bool
    actor_type: ActorType
    # API-key callers: the key's scopes and (optional) single-KB pin.
    api_key_id: uuid.UUID | None = None
    api_key_scopes: frozenset[ApiKeyScope] = frozenset()
    api_key_kb_id: uuid.UUID | None = None

    @property
    def is_api_key(self) -> bool:
        return self.actor_type is ActorType.API_KEY

    def has_scope(self, scope: ApiKeyScope) -> bool:
        # Session (JWT) callers are not scope-limited; API keys are.
        return not self.is_api_key or scope in self.api_key_scopes

    def key_allows_kb(self, kb_id: uuid.UUID) -> bool:
        return self.api_key_kb_id is None or self.api_key_kb_id == kb_id
