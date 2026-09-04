"""Near-duplicate suppression over the fused candidate list (docs/ARCHITECTURE.md
section 11.4)."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from app.core.models import ScoredChunk

_WS = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _WS.sub(" ", text.strip().casefold())


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def suppress_duplicates(
    candidates: Sequence[ScoredChunk], *, cosine_threshold: float
) -> list[ScoredChunk]:
    kept: list[ScoredChunk] = []
    kept_texts: list[str] = []
    for cand in candidates:
        norm = _normalise(cand.content)
        if norm and norm in kept_texts:
            continue
        is_dup = False
        if cand.dense is not None:
            for other in kept:
                if other.dense is not None and _cosine(cand.dense, other.dense) >= cosine_threshold:
                    is_dup = True
                    break
        if is_dup:
            continue
        kept.append(cand)
        kept_texts.append(norm)
    return kept
