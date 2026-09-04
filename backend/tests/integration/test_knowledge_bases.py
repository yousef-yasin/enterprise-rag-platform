"""Knowledge bases: CRUD, membership, the role matrix, audit (Phase 1 gate)."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AuditAction
from app.infra.db.models import AuditLog
from tests.integration._helpers import auth, create_kb, login, register, register_and_auth


async def test_create_lists_and_get_kb(client: AsyncClient) -> None:
    headers = await register_and_auth(client, email="owner@example.com")
    kb = await create_kb(client, headers, slug="handbook")
    assert kb["your_role"] == "owner"

    listed = await client.get("/api/v1/knowledge-bases", headers=headers)
    assert listed.status_code == 200
    assert [item["slug"] for item in listed.json()["items"]] == ["handbook"]

    got = await client.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=headers)
    assert got.status_code == 200


async def test_slug_uniqueness(client: AsyncClient) -> None:
    headers = await register_and_auth(client, email="owner@example.com")
    await create_kb(client, headers, slug="handbook")
    dup = await client.post(
        "/api/v1/knowledge-bases", headers=headers, json={"name": "X", "slug": "handbook"}
    )
    assert dup.status_code == 409


async def test_non_member_gets_404(client: AsyncClient) -> None:
    owner = await register_and_auth(client, email="owner@example.com")
    kb = await create_kb(client, owner, slug="handbook")

    # second user, not a member
    await register(client, email="stranger@example.com", as_admin=owner)
    stranger = auth(await login(client, email="stranger@example.com"))
    resp = await client.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=stranger)
    assert resp.status_code == 404


async def test_role_matrix(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await register_and_auth(client, email="owner@example.com")
    kb = await create_kb(client, owner, slug="handbook")

    await register(client, email="viewer@example.com", as_admin=owner)
    await register(client, email="editor@example.com", as_admin=owner)

    for email, role in (("viewer@example.com", "viewer"), ("editor@example.com", "editor")):
        r = await client.post(
            f"/api/v1/knowledge-bases/{kb['id']}/members",
            headers=owner,
            json={"email": email, "role": role},
        )
        assert r.status_code == 201, r.text

    viewer = auth(await login(client, email="viewer@example.com"))
    editor = auth(await login(client, email="editor@example.com"))

    # viewer can read, cannot manage members
    assert (
        await client.get(f"/api/v1/knowledge-bases/{kb['id']}", headers=viewer)
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/knowledge-bases/{kb['id']}/members", headers=viewer)
    ).status_code == 404  # needs owner

    # editor also cannot manage members or delete the KB
    assert (
        await client.patch(
            f"/api/v1/knowledge-bases/{kb['id']}", headers=editor, json={"name": "x"}
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=editor)
    ).status_code == 404

    # owner can update + delete
    assert (
        await client.patch(
            f"/api/v1/knowledge-bases/{kb['id']}", headers=owner, json={"name": "Renamed"}
        )
    ).status_code == 200

    audit_rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.knowledge_base_id == kb["id"])))
        .scalars()
        .all()
    )
    actions = {row.action for row in audit_rows}
    assert AuditAction.KB_CREATE in actions
    assert AuditAction.MEMBER_ADD in actions


async def test_cannot_grant_owner_role(client: AsyncClient) -> None:
    owner = await register_and_auth(client, email="owner@example.com")
    kb = await create_kb(client, owner, slug="handbook")
    await register(client, email="x@example.com", as_admin=owner)
    r = await client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/members",
        headers=owner,
        json={"email": "x@example.com", "role": "owner"},
    )
    assert r.status_code == 422


async def test_delete_kb_cascades(client: AsyncClient, db_session: AsyncSession) -> None:
    from app.infra.db.models import KnowledgeBase, KnowledgeBaseMember

    owner = await register_and_auth(client, email="owner@example.com")
    kb = await create_kb(client, owner, slug="handbook")
    resp = await client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=owner)
    assert resp.status_code == 204

    db_session.expire_all()
    assert await db_session.get(KnowledgeBase, kb["id"]) is None
    members = (await db_session.execute(select(KnowledgeBaseMember))).scalars().all()
    assert members == []
