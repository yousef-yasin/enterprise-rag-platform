"""Knowledge base management (docs/ARCHITECTURE.md §25)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.enums import AuditAction, KBRole
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.principal import Principal
from app.infra.db.models import KnowledgeBase, KnowledgeBaseMember
from app.infra.db.repositories.audit import AuditRepository
from app.infra.db.repositories.knowledge_bases import KnowledgeBaseRepository
from app.infra.db.repositories.users import UserRepository


@dataclass(frozen=True, slots=True)
class MemberView:
    member: KnowledgeBaseMember
    email: str
    display_name: str


class KnowledgeBaseService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._kbs = KnowledgeBaseRepository(session)
        self._users = UserRepository(session)
        self._audit = AuditRepository(session)

    async def create(
        self,
        principal: Principal,
        *,
        name: str,
        slug: str,
        description: str | None,
        request_id: str | None,
    ) -> KnowledgeBase:
        if await self._kbs.slug_exists(slug):
            raise ConflictError("a knowledge base with that slug already exists")
        kb = self._kbs.add(
            name=name, slug=slug, description=description, owner_id=principal.user_id
        )
        await self._session.flush()
        self._kbs.add_member(
            kb_id=kb.id, user_id=principal.user_id, role=KBRole.OWNER, added_by=principal.user_id
        )
        self._audit.record(
            actor_type=principal.actor_type,
            actor_id=principal.user_id,
            action=AuditAction.KB_CREATE,
            target_type="knowledge_base",
            target_id=kb.id,
            knowledge_base_id=kb.id,
            meta={"slug": slug},
            request_id=request_id,
        )
        return kb

    async def list_for(
        self, principal: Principal, *, limit: int, offset: int
    ) -> list[KnowledgeBase]:
        return await self._kbs.list_for_user(
            principal.user_id, is_admin=principal.is_admin, limit=limit, offset=offset
        )

    async def update(
        self, kb: KnowledgeBase, *, name: str | None, description: str | None
    ) -> KnowledgeBase:
        if name is not None:
            kb.name = name
        if description is not None:
            kb.description = description
        return kb

    async def delete(
        self, kb: KnowledgeBase, principal: Principal, *, request_id: str | None
    ) -> None:
        # Phase 3+: the reindex/purge path also drops the Qdrant collection.
        self._audit.record(
            actor_type=principal.actor_type,
            actor_id=principal.user_id,
            action=AuditAction.KB_DELETE,
            target_type="knowledge_base",
            target_id=kb.id,
            knowledge_base_id=kb.id,
            meta={"slug": kb.slug},
            request_id=request_id,
        )
        await self._session.flush()
        await self._kbs.delete(kb)

    # ── membership ─────────────────────────────────────────────────────────
    async def list_members(self, kb: KnowledgeBase) -> list[MemberView]:
        members = await self._kbs.list_members(kb.id)
        views: list[MemberView] = []
        for member in members:
            user = await self._users.get(member.user_id)
            views.append(
                MemberView(
                    member=member,
                    email=user.email if user else "(deleted)",
                    display_name=user.display_name if user else "(deleted)",
                )
            )
        return views

    async def add_member(
        self,
        kb: KnowledgeBase,
        principal: Principal,
        *,
        email: str,
        role: KBRole,
        request_id: str | None,
    ) -> MemberView:
        user = await self._users.get_by_email(email)
        if user is None:
            raise NotFoundError("no user with that email")
        if user.id == kb.owner_id:
            raise ValidationError("the owner is already a member")
        existing = await self._kbs.get_membership(kb.id, user.id)
        if existing is not None:
            existing.role = role
            member = existing
        else:
            member = self._kbs.add_member(
                kb_id=kb.id, user_id=user.id, role=role, added_by=principal.user_id
            )
        self._audit.record(
            actor_type=principal.actor_type,
            actor_id=principal.user_id,
            action=AuditAction.MEMBER_ADD,
            target_type="user",
            target_id=user.id,
            knowledge_base_id=kb.id,
            meta={"role": role.value},
            request_id=request_id,
        )
        return MemberView(member=member, email=user.email, display_name=user.display_name)

    async def remove_member(
        self,
        kb: KnowledgeBase,
        principal: Principal,
        *,
        user_id: uuid.UUID,
        request_id: str | None,
    ) -> None:
        if user_id == kb.owner_id:
            raise ValidationError("cannot remove the owner")
        membership = await self._kbs.get_membership(kb.id, user_id)
        if membership is None:
            raise NotFoundError("membership not found")
        await self._kbs.remove_member(kb.id, user_id)
        self._audit.record(
            actor_type=principal.actor_type,
            actor_id=principal.user_id,
            action=AuditAction.MEMBER_REMOVE,
            target_type="user",
            target_id=user_id,
            knowledge_base_id=kb.id,
            request_id=request_id,
        )
