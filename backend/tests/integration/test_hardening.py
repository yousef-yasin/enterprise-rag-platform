"""Phase 10 — rate limiting + Prometheus metrics (docs/ARCHITECTURE.md §22, §28.4)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from tests.integration._helpers import register_and_auth


async def test_metrics_endpoint_exposes_rag_series(client: AsyncClient) -> None:
    # generate a little traffic first
    await register_and_auth(client, email="m@example.com")
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    assert "rag_http_requests_total" in body
    assert "rag_http_request_duration_seconds" in body
    # metrics route itself is excluded from the HTTP counters
    assert 'path="/metrics"' not in body


async def test_rate_limit_returns_429_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "5")
    monkeypatch.setenv("RATE_LIMIT_BURST", "5")
    get_settings.cache_clear()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://ratelimit.test") as c:
        seen_429 = False
        retry_after = None
        for _ in range(25):
            r = await c.get("/api/v1/knowledge-bases")  # 401 (no auth) but still rate-limited
            if r.status_code == 429:
                seen_429 = True
                retry_after = r.headers.get("retry-after")
                assert r.json()["error"]["code"] == "rate_limited"
                break
        assert seen_429, "expected a 429 after exceeding the configured limit"
        assert retry_after is not None and int(retry_after) >= 1

    get_settings.cache_clear()


async def test_health_endpoints_are_exempt_from_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "3")
    monkeypatch.setenv("RATE_LIMIT_BURST", "3")
    get_settings.cache_clear()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://health.test") as c:
        for _ in range(20):
            r = await c.get("/health/live")
            assert r.status_code == 200

    get_settings.cache_clear()
