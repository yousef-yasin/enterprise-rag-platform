"""Auth: register / login / refresh / logout / me + failure modes
(Phase 1 gate + §24.2 cookie/CSRF model)."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration._helpers import auth, csrf_headers, login, register


async def test_first_user_is_admin_and_can_login(client: AsyncClient) -> None:
    body = await register(client, email="admin@example.com")
    assert body["is_admin"] is True

    token = await login(client, email="admin@example.com")
    me = await client.get("/api/v1/auth/me", headers=auth(token))
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"
    assert me.json()["is_admin"] is True


async def test_open_registration_disabled_by_default(client: AsyncClient) -> None:
    await register(client, email="admin@example.com")
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "second@example.com", "password": "password123"},
    )
    assert resp.status_code == 403


async def test_login_rejects_bad_password(client: AsyncClient) -> None:
    await register(client, email="admin@example.com")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_login_sets_httponly_refresh_cookie_and_csrf_cookie(client: AsyncClient) -> None:
    await register(client, email="admin@example.com")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    assert "refresh_token" not in resp.json()

    set_cookie = " ".join(resp.headers.get_list("set-cookie"))
    assert "rag_refresh=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie
    assert "rag_csrf=" in set_cookie
    # the CSRF cookie must be JS-readable (no HttpOnly on that one)
    csrf_line = next(c for c in resp.headers.get_list("set-cookie") if c.startswith("rag_csrf="))
    assert "HttpOnly" not in csrf_line

    assert client.cookies.get("rag_refresh") is not None
    assert client.cookies.get("rag_csrf") is not None


async def test_refresh_with_cookie_and_csrf_issues_new_access_token(client: AsyncClient) -> None:
    await register(client, email="admin@example.com")
    await login(client, email="admin@example.com")

    resp = await client.post("/api/v1/auth/refresh", headers=csrf_headers(client))
    assert resp.status_code == 200
    new_access = resp.json()["access_token"]
    assert "refresh_token" not in resp.json()
    # the session + CSRF cookies are re-issued (fresh Max-Age window). v1 has no
    # refresh-token denylist (out of scope, §25) so the old token is not revoked.
    set_cookie = " ".join(resp.headers.get_list("set-cookie"))
    assert "rag_refresh=" in set_cookie and "rag_csrf=" in set_cookie

    me = await client.get("/api/v1/auth/me", headers=auth(new_access))
    assert me.status_code == 200


async def test_refresh_without_csrf_header_is_forbidden(client: AsyncClient) -> None:
    await register(client, email="admin@example.com")
    await login(client, email="admin@example.com")

    resp = await client.post("/api/v1/auth/refresh")  # cookie present, header missing
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


async def test_refresh_with_mismatched_csrf_is_forbidden(client: AsyncClient) -> None:
    await register(client, email="admin@example.com")
    await login(client, email="admin@example.com")

    resp = await client.post("/api/v1/auth/refresh", headers={"x-csrf-token": "not-the-cookie"})
    assert resp.status_code == 403


async def test_refresh_without_session_cookie_is_forbidden(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/refresh", headers={"x-csrf-token": "anything"})
    assert resp.status_code == 403


async def test_access_token_cannot_be_used_as_refresh(client: AsyncClient) -> None:
    await register(client, email="admin@example.com")
    token = await login(client, email="admin@example.com")

    # overwrite the session cookie with the (wrong-type) access token
    client.cookies.delete("rag_refresh", domain="api.test", path="/api/v1/auth")
    client.cookies.set("rag_refresh", token, domain="api.test", path="/api/v1/auth")
    resp = await client.post("/api/v1/auth/refresh", headers=csrf_headers(client))
    assert resp.status_code == 401


async def test_logout_clears_cookies_and_kills_the_session(client: AsyncClient) -> None:
    await register(client, email="admin@example.com")
    await login(client, email="admin@example.com")

    resp = await client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert resp.status_code == 204

    # cookies are gone; a subsequent refresh cannot succeed
    assert not client.cookies.get("rag_refresh")
    again = await client.post("/api/v1/auth/refresh", headers={"x-csrf-token": "x"})
    assert again.status_code == 403


async def test_logout_without_session_is_a_noop_success(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204


async def test_unauthenticated_request_is_rejected(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
