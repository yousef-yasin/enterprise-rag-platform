"""Knowledge base + membership persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import KBRole
from app.infra.db.models import KnowledgeBase, KnowledgeBaseMember


class KnowledgeBaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, kb_id: uuid.UUID) -> KnowledgeBase | None:
        return await self._session.get(KnowledgeBase, kb_id)

    async def get_by_slug(self, slug: str) -> KnowledgeBase | None:
        result = await self._session.execute(
            select(KnowledgeBase).where(KnowledgeBase.slug == slug)
        )
        return result.scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        result = await self._session.execute(
            select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.slug == slug)
        )
        return bool(result.scalar_one())

    async def list_for_user(
        self, user_id: uuid.UUID, *, is_admin: bool, limit: int, offset: int
    ) -> list[KnowledgeBase]:
        stmt = select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
        if not is_admin:
            member_kb_ids = select(KnowledgeBaseMember.knowledge_base_id).where(
                KnowledgeBaseMember.user_id == user_id
            )
            stmt = stmt.where(
                or_(
                    KnowledgeBase.owner_id == user_id,
                    KnowledgeBase.id.in_(member_kb_ids),
                )
            )
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def add(
        self,
        *,
        name: str,
        slug: str,
        description: str | None,
        owner_id: uuid.UUID,
    ) -> KnowledgeBase:
        kb = KnowledgeBase(name=name, slug=slug, description=description, owner_id=owner_id)
        self._session.add(kb)
        return kb

    async def delete(self, kb: KnowledgeBase) -> None:
        await self._session.delete(kb)

    # ── membership ──────────────────────────────────────────────────────────
    async def get_membership(
        self, kb_id: uuid.UUID, user_id: uuid.UUID
    ) -> KnowledgeBaseMember | None:
        return await self._session.get(
            KnowledgeBaseMember, {"knowledge_base_id": kb_id, "user_id": user_id}
        )

    async def list_members(self, kb_id: uuid.UUID) -> list[KnowledgeBaseMember]:
        result = await self._session.execute(
            select(KnowledgeBaseMember)
            .where(KnowledgeBaseMember.knowledge_base_id == kb_id)
            .order_by(KnowledgeBaseMember.added_at)
        )
        return list(result.scalars().all())

    def add_member(
        self,
        *,
        kb_id: uuid.UUID,
        user_id: uuid.UUID,
        role: KBRole,
        added_by: uuid.UUID | None,
    ) -> KnowledgeBaseMember:
        member = KnowledgeBaseMember(
            knowledge_base_id=kb_id,
            user_id=user_id,
            role=role,
            added_by=added_by,
            added_at=datetime.now(UTC),
        )
        self._session.add(member)
        return member

    async def remove_member(self, kb_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(KnowledgeBaseMember).where(
                KnowledgeBaseMember.knowledge_base_id == kb_id,
                KnowledgeBaseMember.user_id == user_id,
            )
        )
