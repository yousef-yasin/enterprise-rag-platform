"""RAG chat: citations, abstention, streaming, multi-turn, conversations, feedback
(Phase 6-7 + 9 gate)."""

from __future__ import annotations

import json
import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.infra.db.models import Citation, Message, RetrievalTrace
from app.services.ingestion import IngestionPipeline
from tests.integration._helpers import create_kb, register_and_auth
from tests.integration.test_ingestion import _MD


async def _seed(client: AsyncClient, headers: dict[str, str]) -> str:
    kb = await create_kb(client, headers, slug="handbook")
    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        headers=headers,
        files={"file": ("handbook.md", _MD, "text/markdown")},
    )
    await IngestionPipeline(get_settings()).run(resp.json()["id"])
    return str(kb["id"])


async def test_chat_answers_with_citations(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await register_and_auth(client, email="o@example.com")
    kb_id = await _seed(client, headers)

    resp = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={"knowledge_base_id": kb_id, "message": "What benefits does the company offer?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["abstained"] is False
    assert "[[1]]" in body["answer"]
    assert body["citations"]
    assert body["citations"][0]["was_cited"] is True
    assert body["conversation_id"] and body["message_id"] and body["trace_id"]

    # every cited chunk was in context (hard check ~100%)
    db_session.expire_all()
    trace = (
        await db_session.execute(
            select(RetrievalTrace).where(RetrievalTrace.id == uuid.UUID(body["trace_id"]))
        )
    ).scalar_one()
    assert set(trace.cited_chunk_ids) <= set(trace.context_chunk_ids)

    cits = (
        (
            await db_session.execute(
                select(Citation).where(Citation.message_id == uuid.UUID(body["message_id"]))
            )
        )
        .scalars()
        .all()
    )
    assert cits and all(c.chunk_content_snapshot for c in cits)


async def test_chat_abstains_on_off_topic(client: AsyncClient) -> None:
    headers = await register_and_auth(client, email="o@example.com")
    kb = await create_kb(client, headers, slug="empty")
    resp = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={"knowledge_base_id": kb["id"], "message": "what is the capital of France?"},
    )
    assert resp.status_code == 200
    assert resp.json()["abstained"] is True
    assert resp.json()["citations"] == []


async def test_chat_stream_emits_tokens_then_done(client: AsyncClient) -> None:
    headers = await register_and_auth(client, email="o@example.com")
    kb_id = await _seed(client, headers)

    events: list[tuple[str, dict[str, object]]] = []
    async with client.stream(
        "POST",
        "/api/v1/chat/stream",
        headers=headers,
        json={"knowledge_base_id": kb_id, "message": "What is the code of conduct?"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        buf = ""
        async for chunk in response.aiter_text():
            buf += chunk
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                etype = ""
                data = "{}"
                for line in raw.splitlines():
                    if line.startswith("event: "):
                        etype = line[7:]
                    elif line.startswith("data: "):
                        data = line[6:]
                if etype:
                    events.append((etype, json.loads(data)))

    types = [e[0] for e in events]
    assert "token" in types
    assert types[-1] == "done"
    done = events[-1][1]
    assert done["message_id"]
    assert "citations" in done


async def test_multi_turn_contextualization(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await register_and_auth(client, email="o@example.com")
    kb_id = await _seed(client, headers)

    first = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={"knowledge_base_id": kb_id, "message": "Tell me about the benefits package."},
    )
    conv_id = first.json()["conversation_id"]

    follow = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={
            "knowledge_base_id": kb_id,
            "conversation_id": conv_id,
            "message": "what about paid leave specifically?",
        },
    )
    assert follow.status_code == 200
    body = follow.json()
    assert not body["abstained"]

    db_session.expire_all()
    msgs = (
        (
            await db_session.execute(
                select(Message).where(Message.conversation_id == uuid.UUID(conv_id))
            )
        )
        .scalars()
        .all()
    )
    assistant_msgs = [m for m in msgs if m.role.value == "assistant"]
    assert len(assistant_msgs) == 2
    # the follow-up ran through the contextualization path and retrieved on the
    # follow-up query (FakeLLM echoes the standalone query verbatim).
    last = sorted(msgs, key=lambda m: m.created_at)[-1]
    assert "leave" in (last.search_query or "").lower()


async def test_conversation_list_get_delete_and_feedback(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await register_and_auth(client, email="o@example.com")
    kb_id = await _seed(client, headers)

    chat = await client.post(
        "/api/v1/chat",
        headers=headers,
        json={"knowledge_base_id": kb_id, "message": "Onboarding steps?"},
    )
    conv_id = chat.json()["conversation_id"]
    message_id = chat.json()["message_id"]

    listing = await client.get("/api/v1/conversations", headers=headers)
    assert conv_id in {c["id"] for c in listing.json()["items"]}

    msgs = await client.get(f"/api/v1/conversations/{conv_id}", headers=headers)
    assert msgs.status_code == 200
    assert len(msgs.json()["items"]) == 2

    fb = await client.post(
        f"/api/v1/messages/{message_id}/feedback",
        headers=headers,
        json={"rating": "up", "reason": "incorrect"},
    )
    assert fb.status_code == 204

    delete = await client.delete(f"/api/v1/conversations/{conv_id}", headers=headers)
    assert delete.status_code == 204
    db_session.expire_all()
    assert (
        await db_session.execute(
            select(Message).where(Message.conversation_id == uuid.UUID(conv_id))
        )
    ).first() is None


async def test_conversation_ownership_enforced(client: AsyncClient) -> None:
    owner = await register_and_auth(client, email="o@example.com")
    kb_id = await _seed(client, owner)
    chat = await client.post(
        "/api/v1/chat", headers=owner, json={"knowledge_base_id": kb_id, "message": "hello"}
    )
    conv_id = chat.json()["conversation_id"]

    from tests.integration._helpers import auth, register

    await register(client, email="other@example.com", as_admin=owner)
    other = auth(
        (
            await client.post(
                "/api/v1/auth/login", json={"email": "other@example.com", "password": "password123"}
            )
        ).json()["access_token"]
    )
    resp = await client.get(f"/api/v1/conversations/{conv_id}", headers=other)
    assert resp.status_code == 404
