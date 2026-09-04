"""Audit-log persistence (append-only, docs/ARCHITECTURE.md §25.4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType, AuditAction
from app.infra.db.models import AuditLog


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def record(
        self,
        *,
        actor_type: ActorType,
        actor_id: uuid.UUID | None,
        action: AuditAction,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        knowledge_base_id: uuid.UUID | None = None,
        meta: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            knowledge_base_id=knowledge_base_id,
            meta=meta or {},
            request_id=request_id,
            created_at=datetime.now(UTC),
        )
        self._session.add(entry)
        return entry

    async def list_for_kb(self, kb_id: uuid.UUID, *, limit: int, offset: int) -> list[AuditLog]:
        result = await self._session.execute(
            select(AuditLog)
            .where(AuditLog.knowledge_base_id == kb_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
