"""Rank/score fusion of the dense and sparse result lists (docs/ARCHITECTURE.md
section 12, ADR 0003).

The app-side implementations here are the reference. When ``FUSION_STRATEGY=rrf`` and
both channels are healthy the query is executed server-side by Qdrant with the same
semantics; this module handles the ``weighted_norm`` / ``dbsf`` paths and the
sparse-degraded fallback.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.enums import FusionStrategy


@dataclass(frozen=True, slots=True)
class Ranked:
    id: str
    score: float


def _rank_map(items: Sequence[Ranked]) -> dict[str, int]:
    return {item.id: rank for rank, item in enumerate(items)}


def reciprocal_rank_fusion(
    dense: Sequence[Ranked],
    sparse: Sequence[Ranked],
    *,
    k: int = 60,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0,
) -> list[Ranked]:
    scores: dict[str, float] = {}
    for weight, items in ((dense_weight, dense), (sparse_weight, sparse)):
        for rank, item in enumerate(items):
            scores[item.id] = scores.get(item.id, 0.0) + weight * (1.0 / (k + rank + 1))
    return _sorted(scores)


def _minmax(items: Sequence[Ranked]) -> dict[str, float]:
    if not items:
        return {}
    values = [i.score for i in items]
    lo, hi = min(values), max(values)
    span = hi - lo
    if span <= 0:
        return {i.id: 1.0 for i in items}
    return {i.id: (i.score - lo) / span for i in items}


def weighted_norm_fusion(
    dense: Sequence[Ranked],
    sparse: Sequence[Ranked],
    *,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0,
) -> list[Ranked]:
    d, s = _minmax(dense), _minmax(sparse)
    scores: dict[str, float] = {}
    for cid, value in d.items():
        scores[cid] = scores.get(cid, 0.0) + dense_weight * value
    for cid, value in s.items():
        scores[cid] = scores.get(cid, 0.0) + sparse_weight * value
    return _sorted(scores)


def _zscore(items: Sequence[Ranked]) -> dict[str, float]:
    if not items:
        return {}
    values = [i.score for i in items]
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    std = var**0.5 or 1.0
    return {i.id: (i.score - mean) / std for i in items}


def dbsf_fusion(dense: Sequence[Ranked], sparse: Sequence[Ranked]) -> list[Ranked]:
    d, s = _zscore(dense), _zscore(sparse)
    scores: dict[str, float] = {}
    for cid, value in d.items():
        scores[cid] = scores.get(cid, 0.0) + value
    for cid, value in s.items():
        scores[cid] = scores.get(cid, 0.0) + value
    return _sorted(scores)


def _sorted(scores: dict[str, float]) -> list[Ranked]:
    return [
        Ranked(cid, score)
        for cid, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    ]


def fuse(
    dense: Sequence[Ranked],
    sparse: Sequence[Ranked],
    *,
    strategy: FusionStrategy,
    rrf_k: int,
    dense_weight: float,
    sparse_weight: float,
    limit: int,
) -> list[Ranked]:
    if not sparse:
        return list(dense)[:limit]
    if not dense:
        return list(sparse)[:limit]
    if strategy is FusionStrategy.RRF:
        fused = reciprocal_rank_fusion(
            dense, sparse, k=rrf_k, dense_weight=dense_weight, sparse_weight=sparse_weight
        )
    elif strategy is FusionStrategy.WEIGHTED_NORM:
        fused = weighted_norm_fusion(
            dense, sparse, dense_weight=dense_weight, sparse_weight=sparse_weight
        )
    else:
        fused = dbsf_fusion(dense, sparse)
    return fused[:limit]
