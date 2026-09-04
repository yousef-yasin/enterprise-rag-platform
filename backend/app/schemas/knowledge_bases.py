"""Knowledge base + membership DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.enums import KBRole
from app.infra.db.models import KnowledgeBase, KnowledgeBaseMember

_SLUG_ALLOWED = set("abcdefghijklmnopqrstuvwxyz0123456789-")


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        slug = value.strip().lower()
        if not slug or set(slug) - _SLUG_ALLOWED or slug.startswith("-") or slug.endswith("-"):
            raise ValueError("slug must be lowercase alphanumeric with hyphens")
        return slug


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class KnowledgeBaseResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    owner_id: uuid.UUID
    active_embedding_profile_id: str | None
    your_role: KBRole
    created_at: datetime

    @classmethod
    def from_model(cls, kb: KnowledgeBase, *, your_role: KBRole) -> KnowledgeBaseResponse:
        return cls(
            id=kb.id,
            name=kb.name,
            slug=kb.slug,
            description=kb.description,
            owner_id=kb.owner_id,
            active_embedding_profile_id=kb.active_embedding_profile_id,
            your_role=your_role,
            created_at=kb.created_at,
        )


class MemberAddRequest(BaseModel):
    email: EmailStr
    role: KBRole

    @field_validator("role")
    @classmethod
    def _no_owner(cls, value: KBRole) -> KBRole:
        if value is KBRole.OWNER:
            raise ValueError("cannot grant the owner role; transfer ownership instead")
        return value


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: KBRole
    added_at: datetime

    @classmethod
    def from_model(
        cls, member: KnowledgeBaseMember, *, email: str, display_name: str
    ) -> MemberResponse:
        return cls(
            user_id=member.user_id,
            email=email,
            display_name=display_name,
            role=member.role,
            added_at=member.added_at,
        )
