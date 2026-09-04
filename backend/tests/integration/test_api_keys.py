"""API keys: create / list / revoke / scope ∩ membership enforcement (Phase 1 gate)."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration._helpers import auth, create_kb, register_and_auth


async def test_api_key_lifecycle_and_scoped_access(client: AsyncClient) -> None:
    headers = await register_and_auth(client, email="owner@example.com")
    kb = await create_kb(client, headers, slug="handbook")

    created = await client.post(
        "/api/v1/api-keys",
        headers=headers,
        json={"name": "ci", "scopes": ["kb:read"], "knowledge_base_id": kb["id"]},
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    assert token.startswith("rag_")

    key_headers = auth(token)
    # kb:read scope -> can read the pinned KB
    assert (
        await client.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=key_headers)
    ).status_code == 200
    # cannot manage (no kb:manage scope) -> 404
    assert (
        await client.get(f"/api/v1/knowledge-bases/{kb['id']}/members", headers=key_headers)
    ).status_code == 404
    # cannot create another KB (that is a session-only action; api keys can't create keys either)
    assert (
        await client.post(
            "/api/v1/api-keys",
            headers=key_headers,
            json={"name": "x", "scopes": ["kb:read"]},
        )
    ).status_code == 422

    listed = await client.get("/api/v1/api-keys", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["key_prefix"] == token[:12]

    key_id = created.json()["id"]
    assert (await client.delete(f"/api/v1/api-keys/{key_id}", headers=headers)).status_code == 204
    # revoked -> now unauthorized
    assert (
        await client.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=key_headers)
    ).status_code == 401


async def test_key_pinned_to_kb_cannot_reach_other_kb(client: AsyncClient) -> None:
    headers = await register_and_auth(client, email="owner@example.com")
    kb_a = await create_kb(client, headers, slug="alpha")
    kb_b = await create_kb(client, headers, slug="beta")

    created = await client.post(
        "/api/v1/api-keys",
        headers=headers,
        json={"name": "pinned", "scopes": ["kb:read"], "knowledge_base_id": kb_a["id"]},
    )
    key_headers = auth(created.json()["token"])
    assert (
        await client.get(f"/api/v1/knowledge-bases/{kb_a['id']}", headers=key_headers)
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/knowledge-bases/{kb_b['id']}", headers=key_headers)
    ).status_code == 404
