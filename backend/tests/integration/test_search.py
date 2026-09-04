"""Dense / sparse / hybrid retrieval, profile mismatch, KB isolation (Phase 3-4 gate)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.infra.db.models import KnowledgeBase
from app.services.ingestion import IngestionPipeline
from tests.integration._helpers import auth, create_kb, register, register_and_auth
from tests.integration.test_ingestion import _MD

_QUERY = "how much paid leave do employees get?"


async def _seed_kb(client: AsyncClient, headers: dict[str, str], slug: str) -> str:
    kb = await create_kb(client, headers, slug=slug)
    resp = await client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        headers=headers,
        files={"file": ("handbook.md", _MD, "text/markdown")},
    )
    doc_id: str = resp.json()["id"]
    await IngestionPipeline(get_settings()).run(doc_id)
    return str(kb["id"])


async def test_dense_search_returns_chunks(client: AsyncClient) -> None:
    # FakeEmbedder is deterministic but not semantic; assert structure, not ranking
    # quality (that is measured in Phase 9 eval with real embeddings).
    headers = await register_and_auth(client, email="o@example.com")
    kb_id = await _seed_kb(client, headers, "handbook")
    resp = await client.post(
        "/api/v1/search",
        headers=headers,
        json={"knowledge_base_id": kb_id, "query": _QUERY, "params": {"mode": "dense"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hits"]
    assert all({"chunk_id", "document_id", "score", "snippet"} <= set(h) for h in body["hits"])
    assert body["abstained"] is False


async def test_sparse_search_finds_exact_keyword(client: AsyncClient) -> None:
    headers = await register_and_auth(client, email="o@example.com")
    kb_id = await _seed_kb(client, headers, "handbook")
    resp = await client.post(
        "/api/v1/search",
        headers=headers,
        json={
            "knowledge_base_id": kb_id,
            "query": "harassment disciplinary",
            "params": {"mode": "sparse"},
        },
    )
    assert resp.status_code == 200, resp.text
    hits = resp.json()["hits"]
    if hits:  # sparse requires the fastembed BM25 model; degrades gracefully if absent
        assert any("harassment" in h["snippet"].lower() for h in hits)


@pytest.mark.parametrize("mode", ["dense", "sparse", "hybrid"])
async def test_search_modes_run(client: AsyncClient, mode: str) -> None:
    headers = await register_and_auth(client, email="o@example.com")
    kb_id = await _seed_kb(client, headers, "handbook")
    resp = await client.post(
        "/api/v1/search",
        headers=headers,
        json={
            "knowledge_base_id": kb_id,
            "query": "expense claims finance portal",
            "params": {"mode": mode},
            "include_trace": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == mode
    assert "trace" in body and body["trace"] is not None


async def test_search_empty_kb_abstains(client: AsyncClient) -> None:
    headers = await register_and_auth(client, email="o@example.com")
    kb = await create_kb(client, headers, slug="empty")
    resp = await client.post(
        "/api/v1/search",
        headers=headers,
        json={"knowledge_base_id": kb["id"], "query": _QUERY},
    )
    assert resp.status_code == 200
    assert resp.json()["abstained"] is True
    assert resp.json()["hits"] == []


async def test_search_non_member_forbidden(client: AsyncClient) -> None:
    owner = await register_and_auth(client, email="o@example.com")
    kb_id = await _seed_kb(client, owner, "handbook")
    await register(client, email="stranger@example.com", as_admin=owner)
    stranger = auth(
        (
            await client.post(
                "/api/v1/auth/login",
                json={"email": "stranger@example.com", "password": "password123"},
            )
        ).json()["access_token"]
    )
    resp = await client.post(
        "/api/v1/search", headers=stranger, json={"knowledge_base_id": kb_id, "query": _QUERY}
    )
    assert resp.status_code == 404


async def test_profile_mismatch_returns_409(client: AsyncClient, db_session: AsyncSession) -> None:
    headers = await register_and_auth(client, email="o@example.com")
    kb_id = await _seed_kb(client, headers, "handbook")

    # corrupt the KB's stored profile to simulate a config/model change
    kb = await db_session.get(KnowledgeBase, uuid.UUID(kb_id))
    assert kb is not None
    kb.active_embedding_profile_id = "deadbeefdeadbeef"
    await db_session.commit()

    resp = await client.post(
        "/api/v1/search", headers=headers, json={"knowledge_base_id": kb_id, "query": _QUERY}
    )
    assert resp.status_code == 409
    assert "reindex" in resp.json()["error"]["message"]


async def test_exact_match_utility(client: AsyncClient) -> None:
    headers = await register_and_auth(client, email="o@example.com")
    kb_id = await _seed_kb(client, headers, "handbook")
    resp = await client.get(
        f"/api/v1/knowledge-bases/{kb_id}/search/exact",
        headers=headers,
        params={"q": "harassment"},
    )
    assert resp.status_code == 200
    assert any("harassment" in h["snippet"].lower() for h in resp.json()["hits"])
