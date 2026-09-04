"""Vector store abstraction (docs/ARCHITECTURE.md §9, §20). Adapter (Qdrant) lands
in Phase 3.

Only the boundary is fixed here. Method signatures gain their payload/point types
in Phase 3 alongside the first implementation and the write protocol (§9.2).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class VectorStore(Protocol):
    async def ensure_collection(self, name: str, *, dense_dim: int) -> None:
        """Idempotently create the collection and its payload indexes (§20)."""
        ...

    async def upsert(self, collection: str, points: Sequence[object]) -> None:
        """Batch upsert; ``points`` becomes a typed model in Phase 3."""
        ...

    async def delete_points(self, collection: str, point_ids: Sequence[str]) -> None: ...

    async def count(self, collection: str) -> int: ...
