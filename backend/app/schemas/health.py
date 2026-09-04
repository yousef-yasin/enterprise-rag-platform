"""Health / readiness response models (docs/ARCHITECTURE.md §23.1, §28.2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.health import DependencyState, ReadinessReport


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"


class DependencyStatusModel(BaseModel):
    name: str
    state: Literal["ok", "fail"]
    latency_ms: float
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    dependencies: list[DependencyStatusModel] = Field(default_factory=list)

    @classmethod
    def from_report(cls, report: ReadinessReport) -> ReadinessResponse:
        return cls(
            status="ready" if report.ready else "not_ready",
            dependencies=[
                DependencyStatusModel(
                    name=dep.name,
                    state="ok" if dep.state is DependencyState.OK else "fail",
                    latency_ms=dep.latency_ms,
                    detail=dep.detail,
                )
                for dep in report.dependencies
            ],
        )
