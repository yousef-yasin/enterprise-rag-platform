"""Content hashing (docs/ARCHITECTURE.md §5.1, §8.3)."""

from __future__ import annotations

import hashlib


def content_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
