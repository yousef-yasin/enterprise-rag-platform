"""API key persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.models import ApiKey


class ApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key_id: uuid.UUID) -> ApiKey | None:
        return await self._session.get(ApiKey, key_id)

    async def get_by_prefix(self, prefix: str) -> ApiKey | None:
        result = await self._session.execute(select(ApiKey).where(ApiKey.key_prefix == prefix))
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[ApiKey]:
        result = await self._session.execute(
            select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    def add(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        key_prefix: str,
        key_hash: str,
        scopes: list[str],
        knowledge_base_id: uuid.UUID | None,
    ) -> ApiKey:
        key = ApiKey(
            user_id=user_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            scopes=scopes,
            knowledge_base_id=knowledge_base_id,
        )
        self._session.add(key)
        return key

    async def touch(self, key: ApiKey) -> None:
        key.last_used_at = datetime.now(UTC)

    async def revoke(self, key: ApiKey) -> None:
        key.revoked_at = datetime.now(UTC)
