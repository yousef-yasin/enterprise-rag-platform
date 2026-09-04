"""Conversation DTOs (docs/ARCHITECTURE.md section 23.1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.infra.db.models import Conversation, Message


class ConversationCreate(BaseModel):
    knowledge_base_id: uuid.UUID
    title: str = Field(default="New conversation", max_length=300)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    archived: bool | None = None


class ConversationResponse(BaseModel):
    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    title: str
    archived: bool
    total_tokens: int
    total_cost_usd: float
    created_at: datetime

    @classmethod
    def from_model(cls, conv: Conversation) -> ConversationResponse:
        return cls(
            id=conv.id,
            knowledge_base_id=conv.knowledge_base_id,
            title=conv.title,
            archived=conv.archived,
            total_tokens=conv.total_tokens,
            total_cost_usd=float(conv.total_cost_usd),
            created_at=conv.created_at,
        )


class MessageCitation(BaseModel):
    citation_index: int
    document_filename: str | None
    was_cited: bool
    weak: bool
    snippet: str | None


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    model: str | None
    abstained: bool
    low_confidence: bool
    created_at: datetime
    citations: list[MessageCitation] = []

    @classmethod
    def from_model(
        cls, msg: Message, citations: list[MessageCitation] | None = None
    ) -> MessageResponse:
        return cls(
            id=msg.id,
            role=msg.role.value,
            content=msg.content,
            model=msg.model,
            abstained=msg.abstained,
            low_confidence=msg.low_confidence,
            created_at=msg.created_at,
            citations=citations or [],
        )


class FeedbackRequest(BaseModel):
    rating: str = Field(pattern="^(up|down)$")
    reason: str | None = Field(default=None, max_length=32)
    comment: str | None = Field(default=None, max_length=2000)
