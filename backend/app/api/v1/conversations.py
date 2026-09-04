"""Conversation + message + feedback endpoints (docs/ARCHITECTURE.md section 23.1)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import AuthServiceDep, PrincipalDep, SessionDep, SettingsDep
from app.core.enums import ApiKeyScope, KBRole
from app.core.errors import NotFoundError
from app.infra.db.repositories.conversations import (
    ConversationRepository,
    FeedbackRepository,
    MessageRepository,
)
from app.schemas.common import Page
from app.schemas.conversations import (
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    FeedbackRequest,
    MessageCitation,
    MessageResponse,
)

router = APIRouter(tags=["conversations"])


async def _owned(session: SessionDep, principal: PrincipalDep, conversation_id: uuid.UUID):  # type: ignore[no-untyped-def]
    conv = await ConversationRepository(session).get(conversation_id)
    if conv is None or (conv.user_id != principal.user_id and not principal.is_admin):
        raise NotFoundError("conversation not found")
    return conv


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    body: ConversationCreate,
    session: SessionDep,
    settings: SettingsDep,
    principal: PrincipalDep,
    auth: AuthServiceDep,
) -> ConversationResponse:
    kb = await auth.require_kb(
        body.knowledge_base_id, principal, role=KBRole.VIEWER, scope=ApiKeyScope.CHAT
    )
    conv = ConversationRepository(session).add(
        knowledge_base_id=kb.id, user_id=principal.user_id, title=body.title
    )
    await session.flush()
    return ConversationResponse.from_model(conv)


@router.get("/conversations", response_model=Page[ConversationResponse])
async def list_conversations(
    session: SessionDep,
    principal: PrincipalDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[ConversationResponse]:
    rows = await ConversationRepository(session).list_for_user(
        principal.user_id, limit=limit + 1, offset=offset
    )
    has_more = len(rows) > limit
    return Page(
        items=[ConversationResponse.from_model(c) for c in rows[:limit]],
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


@router.get("/conversations/{conversation_id}", response_model=Page[MessageResponse])
async def get_conversation_messages(
    conversation_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[MessageResponse]:
    await _owned(session, principal, conversation_id)
    repo = ConversationRepository(session)
    msgs = await repo.messages_page(conversation_id, limit=limit + 1, offset=offset)
    has_more = len(msgs) > limit
    mrepo = MessageRepository(session)
    items: list[MessageResponse] = []
    for msg in msgs[:limit]:
        cits = await mrepo.citations_for(msg.id)
        items.append(
            MessageResponse.from_model(
                msg,
                [
                    MessageCitation(
                        citation_index=c.citation_index,
                        document_filename=c.document_filename,
                        was_cited=c.was_cited,
                        weak=c.weak,
                        snippet=c.chunk_content_snapshot[:300]
                        if c.chunk_content_snapshot
                        else None,
                    )
                    for c in cits
                ],
            )
        )
    return Page(items=items, limit=limit, offset=offset, has_more=has_more)


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    session: SessionDep,
    principal: PrincipalDep,
) -> ConversationResponse:
    conv = await _owned(session, principal, conversation_id)
    if body.title is not None:
        conv.title = body.title
    if body.archived is not None:
        conv.archived = body.archived
    return ConversationResponse.from_model(conv)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID, session: SessionDep, principal: PrincipalDep
) -> None:
    conv = await _owned(session, principal, conversation_id)
    await session.delete(conv)


@router.post("/messages/{message_id}/feedback", status_code=204)
async def submit_feedback(
    message_id: uuid.UUID,
    body: FeedbackRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> None:
    from app.infra.db.models import Message

    msg = await session.get(Message, message_id)
    if msg is None:
        raise NotFoundError("message not found")
    conv = await _owned(session, principal, msg.conversation_id)
    _ = conv
    await FeedbackRepository(session).upsert(
        message_id=message_id,
        user_id=principal.user_id,
        rating=body.rating,
        reason=body.reason,
        comment=body.comment,
    )
