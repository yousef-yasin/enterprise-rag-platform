"""Conversation / message / citation / trace / feedback persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import MessageRole
from app.infra.db.models import (
    Citation,
    Conversation,
    Feedback,
    Message,
    RetrievalTrace,
)


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, conversation_id: uuid.UUID) -> Conversation | None:
        return await self._session.get(Conversation, conversation_id)

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[Conversation]:
        result = await self._session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    def add(self, *, knowledge_base_id: uuid.UUID, user_id: uuid.UUID, title: str) -> Conversation:
        conv = Conversation(knowledge_base_id=knowledge_base_id, user_id=user_id, title=title[:300])
        self._session.add(conv)
        return conv

    async def history(self, conversation_id: uuid.UUID, *, limit: int = 40) -> list[Message]:
        result = await self._session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def messages_page(
        self, conversation_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[Message]:
        result = await self._session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(
        self,
        *,
        conversation_id: uuid.UUID,
        role: MessageRole,
        content: str,
        model: str | None = None,
        prompt_version: str | None = None,
        raw_query: str | None = None,
        search_query: str | None = None,
        was_rewritten: bool = False,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        latency_ms: dict[str, Any] | None = None,
        finish_reason: str | None = None,
        abstained: bool = False,
        low_confidence: bool = False,
        degraded: dict[str, Any] | None = None,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            model=model,
            prompt_version=prompt_version,
            raw_query=raw_query,
            search_query=search_query,
            was_rewritten=was_rewritten,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=Decimal(str(estimated_cost_usd)),
            latency_ms=latency_ms or {},
            finish_reason=finish_reason,
            abstained=abstained,
            low_confidence=low_confidence,
            degraded=degraded or {},
            created_at=datetime.now(UTC),
        )
        self._session.add(msg)
        return msg

    def add_citation(
        self,
        *,
        message_id: uuid.UUID,
        citation_index: int,
        chunk_id: uuid.UUID | None,
        document_id: uuid.UUID | None,
        score: float | None,
        was_cited: bool,
        weak: bool,
        chunk_content_snapshot: str | None,
        document_filename: str | None,
    ) -> Citation:
        cit = Citation(
            message_id=message_id,
            citation_index=citation_index,
            chunk_id=chunk_id,
            document_id=document_id,
            score=Decimal(str(score)) if score is not None else None,
            was_cited=was_cited,
            weak=weak,
            chunk_content_snapshot=chunk_content_snapshot,
            document_filename=document_filename,
        )
        self._session.add(cit)
        return cit

    async def citations_for(self, message_id: uuid.UUID) -> list[Citation]:
        result = await self._session.execute(
            select(Citation)
            .where(Citation.message_id == message_id)
            .order_by(Citation.citation_index)
        )
        return list(result.scalars().all())


class TraceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, **kw: Any) -> RetrievalTrace:
        kw.setdefault("created_at", datetime.now(UTC))
        if "estimated_cost_usd" in kw:
            kw["estimated_cost_usd"] = Decimal(str(kw["estimated_cost_usd"]))
        trace = RetrievalTrace(**kw)
        self._session.add(trace)
        return trace


class FeedbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        rating: str,
        reason: str | None,
        comment: str | None,
    ) -> Feedback:
        result = await self._session.execute(
            select(Feedback).where(Feedback.message_id == message_id, Feedback.user_id == user_id)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.rating = rating
            existing.reason = reason
            existing.comment = comment
            return existing
        fb = Feedback(
            message_id=message_id,
            user_id=user_id,
            rating=rating,
            reason=reason,
            comment=comment,
            created_at=datetime.now(UTC),
        )
        self._session.add(fb)
        return fb
