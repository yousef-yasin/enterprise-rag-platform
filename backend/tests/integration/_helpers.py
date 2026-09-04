"""Shared helpers and constants for integration tests."""

from __future__ import annotations

import os
from typing import Any

from httpx import AsyncClient

PG_HOST = os.environ.get("POSTGRES_HOST", "127.0.0.1")
TEST_DSN = f"postgresql+asyncpg://rag:rag_local_dev@{PG_HOST}:5432/rag"


async def register(
    client: AsyncClient,
    *,
    email: str,
    password: str = "password123",
    display_name: str = "",
    as_admin: dict[str, str] | None = None,
) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/auth/register",
        headers=as_admin or {},
        json={"email": email, "password": password, "display_name": display_name},
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()
    return data


async def login(client: AsyncClient, *, email: str, password: str = "password123") -> str:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    # refresh token is delivered as an HttpOnly cookie, never in the body
    assert "refresh_token" not in resp.json()
    token: str = resp.json()["access_token"]
    return token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def csrf_headers(client: AsyncClient) -> dict[str, str]:
    """The double-submit header the SPA echoes from the non-HttpOnly CSRF cookie."""
    value = client.cookies.get("rag_csrf")
    return {"x-csrf-token": value} if value else {}


async def refresh(client: AsyncClient) -> str:
    resp = await client.post("/api/v1/auth/refresh", headers=csrf_headers(client))
    assert resp.status_code == 200, resp.text
    token: str = resp.json()["access_token"]
    return token


async def register_and_auth(
    client: AsyncClient, *, email: str, password: str = "password123"
) -> dict[str, str]:
    await register(client, email=email, password=password)
    return auth(await login(client, email=email, password=password))


async def create_kb(
    client: AsyncClient, headers: dict[str, str], *, slug: str, name: str | None = None
) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": name or slug.title(), "slug": slug},
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()
    return data
