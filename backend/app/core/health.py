"""Domain model for health / readiness reporting (docs/ARCHITECTURE.md §28.2).

A *probe* is an async callable that checks one dependency and returns its
:class:`DependencyStatus`. The concrete probes live in ``app/infra/*/health.py``;
``app/services/health.py`` composes them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum


class DependencyState(StrEnum):
    OK = "ok"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    name: str
    state: DependencyState
    latency_ms: float
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    dependencies: tuple[DependencyStatus, ...]

    @classmethod
    def from_statuses(cls, statuses: list[DependencyStatus]) -> ReadinessReport:
        return cls(
            ready=all(s.state is DependencyState.OK for s in statuses),
            dependencies=tuple(statuses),
        )


DependencyProbe = Callable[[], Awaitable[DependencyStatus]]
