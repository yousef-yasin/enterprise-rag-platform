"""Application startup, health endpoints, error envelope, request id (Phase 0 gate)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_health_service
from app.core.errors import NotFoundError
from app.core.health import DependencyState, DependencyStatus, ReadinessReport
from app.main import create_app
from app.services.health import HealthService


class _StubHealth(HealthService):
    def __init__(self, ready: bool) -> None:
        super().__init__(())
        self._ready = ready

    async def readiness(self) -> ReadinessReport:
        state = DependencyState.OK if self._ready else DependencyState.FAIL
        return ReadinessReport.from_statuses(
            [
                DependencyStatus("postgres", state, 1.0),
                DependencyStatus("qdrant", DependencyState.OK, 1.0),
                DependencyStatus("redis", DependencyState.OK, 1.0),
            ]
        )


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _use_stub_health(app: FastAPI, *, ready: bool) -> None:
    app.dependency_overrides[get_health_service] = lambda: _StubHealth(ready)


def test_app_builds_and_exposes_openapi(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"]


def test_liveness(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_health_alias(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "alive"}


def test_readiness_all_ok(app: FastAPI, client: TestClient) -> None:
    _use_stub_health(app, ready=True)
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert {d["name"] for d in body["dependencies"]} == {"postgres", "qdrant", "redis"}


def test_readiness_reports_503_when_a_dependency_fails(app: FastAPI, client: TestClient) -> None:
    _use_stub_health(app, ready=False)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_request_id_is_generated_and_echoed(client: TestClient) -> None:
    response = client.get("/health/live")
    generated = response.headers.get("x-request-id")
    assert generated and len(generated) == 32


def test_request_id_is_preserved_when_supplied(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


def test_error_envelope_for_app_error(app: FastAPI, client: TestClient) -> None:
    @app.get("/_test/not-found")
    async def _raise() -> None:
        raise NotFoundError("widget missing")

    response = client.get("/_test/not-found", headers={"X-Request-ID": "rid-1"})
    assert response.status_code == 404
    body = response.json()["error"]
    assert body == {
        "code": "not_found",
        "message": "widget missing",
        "details": {},
        "request_id": "rid-1",
    }


def test_error_envelope_hides_unexpected_errors(app: FastAPI) -> None:
    @app.get("/_test/boom")
    async def _boom() -> None:
        raise RuntimeError("internal detail that must not leak")

    with TestClient(app, raise_server_exceptions=False) as local_client:
        response = local_client.get("/_test/boom")
    assert response.status_code == 500
    body = response.json()["error"]
    assert body["code"] == "internal"
    assert "internal detail" not in body["message"]
