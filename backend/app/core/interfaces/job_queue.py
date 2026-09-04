"""Background job queue abstraction (docs/ARCHITECTURE.md §22, ADR 0002).

Wraps the task queue (arq by default) so the rest of the application never imports
it directly and it stays replaceable. The concrete arq-backed adapter and the task
catalogue land in Phase 2.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class JobQueue(Protocol):
    async def enqueue(self, task: str, *args: object, **kwargs: object) -> str:
        """Enqueue ``task`` by name; return a job id. Job *outcome* is authoritative
        in Postgres, not here (ADR 0002)."""
        ...

    async def health_ok(self) -> bool:
        """True when the queue backend is reachable and the worker heartbeat is fresh."""
        ...
