"""Object storage abstraction (docs/ARCHITECTURE.md §3.2, §5.1). Adapters
(filesystem, S3) land in Phase 2.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        """Store raw bytes under a caller-generated, opaque ``key``."""
        ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...
