"""API key management (docs/ARCHITECTURE.md §25.3)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.enums import ApiKeyScope, AuditAction
from app.core.errors import NotFoundError, ValidationError
from app.core.principal import Principal
from app.core.security import generate_api_key
from app.infra.db.models import ApiKey
from app.infra.db.repositories.api_keys import ApiKeyRepository
from app.infra.db.repositories.audit import AuditRepository
from app.infra.db.repositories.knowledge_bases import KnowledgeBaseRepository


@dataclass(frozen=True, slots=True)
class CreatedApiKey:
    key: ApiKey
    token: str


class ApiKeyService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._keys = ApiKeyRepository(session)
        self._kbs = KnowledgeBaseRepository(session)
        self._audit = AuditRepository(session)

    async def create(
        self,
        principal: Principal,
        *,
        name: str,
        scopes: list[ApiKeyScope],
        knowledge_base_id: uuid.UUID | None,
        request_id: str | None,
    ) -> CreatedApiKey:
        if principal.is_api_key:
            raise ValidationError("API keys cannot create other API keys")
        if knowledge_base_id is not None:
            kb = await self._kbs.get(knowledge_base_id)
            if kb is None:
                raise NotFoundError("knowledge base not found")
            if not principal.is_admin and kb.owner_id != principal.user_id:
                membership = await self._kbs.get_membership(knowledge_base_id, principal.user_id)
                if membership is None:
                    raise ValidationError("you are not a member of that knowledge base")

        generated = generate_api_key()
        key = self._keys.add(
            user_id=principal.user_id,
            name=name,
            key_prefix=generated.prefix,
            key_hash=generated.key_hash,
            scopes=[s.value for s in scopes],
            knowledge_base_id=knowledge_base_id,
        )
        await self._session.flush()
        self._audit.record(
            actor_type=principal.actor_type,
            actor_id=principal.user_id,
            action=AuditAction.APIKEY_CREATE,
            target_type="api_key",
            target_id=key.id,
            knowledge_base_id=knowledge_base_id,
            meta={"scopes": [s.value for s in scopes]},
            request_id=request_id,
        )
        return CreatedApiKey(key=key, token=generated.token)

    async def list_for(self, principal: Principal) -> list[ApiKey]:
        return await self._keys.list_for_user(principal.user_id)

    async def revoke(
        self, principal: Principal, key_id: uuid.UUID, *, request_id: str | None
    ) -> None:
        key = await self._keys.get(key_id)
        if key is None or (key.user_id != principal.user_id and not principal.is_admin):
            raise NotFoundError("API key not found")
        if key.revoked_at is None:
            await self._keys.revoke(key)
            self._audit.record(
                actor_type=principal.actor_type,
                actor_id=principal.user_id,
                action=AuditAction.APIKEY_REVOKE,
                target_type="api_key",
                target_id=key.id,
                request_id=request_id,
            )
