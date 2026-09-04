"""Chat endpoints — JSON and SSE (docs/ARCHITECTURE.md section 23)."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import AuthServiceDep, PrincipalDep, SettingsDep
from app.core.enums import ApiKeyScope, KBRole
from app.schemas.search import ChatRequest, ChatResponse, CitationOut
from app.services.chat import ChatService

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest, settings: SettingsDep, principal: PrincipalDep, auth: AuthServiceDep
) -> ChatResponse:
    kb = await auth.require_kb(
        body.knowledge_base_id, principal, role=KBRole.VIEWER, scope=ApiKeyScope.CHAT
    )
    result = await ChatService(settings).collect(
        kb,
        user_id=principal.user_id,
        message=body.message,
        conversation_id=body.conversation_id,
        mode=body.params.mode,
    )
    return ChatResponse(
        answer=result.answer,
        citations=[CitationOut(**dataclasses.asdict(c)) for c in result.citations],
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        trace_id=result.trace_id,
        abstained=result.abstained,
        low_confidence=result.low_confidence,
        degraded=result.degraded,
        uncited_sentences=result.uncited_sentences,
        usage={
            "prompt_tokens": result.usage.prompt_tokens,
            "completion_tokens": result.usage.completion_tokens,
        },
        cost_usd=result.cost_usd,
    )


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest, settings: SettingsDep, principal: PrincipalDep, auth: AuthServiceDep
) -> StreamingResponse:
    kb = await auth.require_kb(
        body.knowledge_base_id, principal, role=KBRole.VIEWER, scope=ApiKeyScope.CHAT
    )
    service = ChatService(settings)

    async def events() -> AsyncIterator[bytes]:
        async for event in service.answer(
            kb,
            user_id=principal.user_id,
            message=body.message,
            conversation_id=body.conversation_id,
            mode=body.params.mode,
        ):
            etype = event.pop("type")
            yield f"event: {etype}\ndata: {json.dumps(event)}\n\n".encode()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
