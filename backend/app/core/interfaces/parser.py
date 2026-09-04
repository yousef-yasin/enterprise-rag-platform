"""Document parser abstraction (docs/ARCHITECTURE.md §8.2, §11.2). Adapters land in
Phase 2.

A parser turns raw bytes into a *block tree* — headings, paragraphs, list items,
tables and code blocks with page numbers and character offsets — which the
structure-aware chunker (§11.2) consumes. The block model is defined in Phase 2.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DocumentParser(Protocol):
    supported_mime_types: frozenset[str]

    async def parse(self, data: bytes, *, mime_type: str, filename: str) -> object:
        """Return a block tree. Return type becomes ``DocumentTree`` in Phase 2.

        Security limits (archive-bomb, XXE, resource caps) and the failure-reason
        taxonomy are the adapter's responsibility (§30).
        """
        ...
