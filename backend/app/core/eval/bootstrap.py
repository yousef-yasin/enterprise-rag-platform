"""Bootstrap confidence intervals for evaluation aggregates (docs/ARCHITECTURE.md §33.2).

`nan` values are dropped before resampling (a metric can be undefined for a
sample — e.g. recall when a sample has no gold chunks).
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Aggregate:
    value: float
    ci_low: float
    ci_high: float
    n: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "value": _round(self.value),
            "ci_low": _round(self.ci_low),
            "ci_high": _round(self.ci_high),
            "n": self.n,
        }


def _round(x: float) -> float:
    return round(x, 4) if x == x else math.nan


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else math.nan


def bootstrap_mean_ci(
    values: Sequence[float],
    *,
    n_resamples: int = 1000,
    confidence: float = 0.95,
    seed: int = 12345,
) -> Aggregate:
    clean = [float(v) for v in values if v == v]  # drop nan
    if not clean:
        return Aggregate(math.nan, math.nan, math.nan, 0)
    point = _mean(clean)
    if len(clean) == 1 or n_resamples <= 0:
        return Aggregate(point, point, point, len(clean))

    rng = random.Random(seed)
    k = len(clean)
    means: list[float] = []
    for _ in range(n_resamples):
        sample = [clean[rng.randrange(k)] for _ in range(k)]
        means.append(_mean(sample))
    means.sort()
    lo_idx = max(0, int((1 - confidence) / 2 * n_resamples))
    hi_idx = min(n_resamples - 1, int((1 + confidence) / 2 * n_resamples))
    return Aggregate(point, means[lo_idx], means[hi_idx], len(clean))


def diff_ci(
    a: Sequence[float],
    b: Sequence[float],
    *,
    n_resamples: int = 1000,
    confidence: float = 0.95,
    seed: int = 12345,
) -> Aggregate:
    """CI for mean(a) - mean(b) with independent resampling of each arm."""
    ca = [float(v) for v in a if v == v]
    cb = [float(v) for v in b if v == v]
    if not ca or not cb:
        return Aggregate(math.nan, math.nan, math.nan, 0)
    point = _mean(ca) - _mean(cb)
    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(max(1, n_resamples)):
        sa = _mean([ca[rng.randrange(len(ca))] for _ in range(len(ca))])
        sb = _mean([cb[rng.randrange(len(cb))] for _ in range(len(cb))])
        diffs.append(sa - sb)
    diffs.sort()
    lo_idx = max(0, int((1 - confidence) / 2 * len(diffs)))
    hi_idx = min(len(diffs) - 1, int((1 + confidence) / 2 * len(diffs)))
    return Aggregate(point, diffs[lo_idx], diffs[hi_idx], min(len(ca), len(cb)))
