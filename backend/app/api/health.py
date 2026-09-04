"""Health and readiness endpoints (docs/ARCHITECTURE.md §23.1, §28.2).

Mounted at the application root (not under ``/api/v1``) so load balancers and the
container healthcheck reach them without version coupling.

  GET /health/live   liveness — the process is up
  GET /health/ready  readiness — every infrastructure dependency responds
  GET /health        alias for /health/live (architecture §23.1 name)
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import HealthServiceDep
from app.schemas.health import LivenessResponse, ReadinessResponse

health_router = APIRouter(tags=["health"])


@health_router.get("/health/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    return LivenessResponse()


@health_router.get("/health", response_model=LivenessResponse, include_in_schema=False)
async def liveness_alias() -> LivenessResponse:
    return LivenessResponse()


@health_router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def readiness(health: HealthServiceDep, response: Response) -> ReadinessResponse:
    report = await health.readiness()
    if not report.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse.from_report(report)
