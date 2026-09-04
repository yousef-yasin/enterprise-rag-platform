"""Document parsing (docs/ARCHITECTURE.md §8.2, §11.2, §30).

Raw bytes -> a normalised :class:`~app.core.models.DocumentTree` (a block tree the
structure-aware chunker consumes), with the failure-reason taxonomy from §30.3.
"""

from __future__ import annotations

from app.core.parsing.pipeline import SUPPORTED_EXTENSIONS, ParseLimits, parse_document

__all__ = ["SUPPORTED_EXTENSIONS", "ParseLimits", "parse_document"]
