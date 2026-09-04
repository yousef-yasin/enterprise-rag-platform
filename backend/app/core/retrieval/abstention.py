"""Abstention / scoring policy (docs/ARCHITECTURE.md section 14)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.core.models import ScoredChunk

_THRESHOLDS_FILE = Path(__file__).resolve().parents[3] / "config" / "reranker_thresholds.json"


@dataclass(frozen=True, slots=True)
class AbstentionDecision:
    abstain: bool
    reason: str  # "empty_kb" | "no_results" | "low_confidence" | ""
    low_confidence: bool


def load_reranker_threshold(model_id: str) -> float | None:
    try:
        data = json.loads(_THRESHOLDS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    entry = data.get(model_id)
    if isinstance(entry, dict) and "min_score" in entry:
        return float(entry["min_score"])
    return None


def decide(
    candidates: Sequence[ScoredChunk],
    *,
    kb_is_empty: bool,
    abstain_on_empty: bool,
    reranker_model: str | None,
    abstain_min_results: int,
    abstain_fusion_floor: float,
    low_confidence_margin: float,
) -> AbstentionDecision:
    if kb_is_empty and abstain_on_empty:
        return AbstentionDecision(abstain=True, reason="empty_kb", low_confidence=False)
    if not candidates:
        return AbstentionDecision(abstain=True, reason="no_results", low_confidence=False)

    top = candidates[0].score
    threshold = load_reranker_threshold(reranker_model) if reranker_model else None

    if threshold is not None:
        if top < threshold:
            return AbstentionDecision(abstain=True, reason="low_confidence", low_confidence=False)
        low = top < threshold + low_confidence_margin
        return AbstentionDecision(abstain=False, reason="", low_confidence=low)

    if reranker_model is not None:
        # reranker ran but is not calibrated: only zero-results gates abstention
        # (reranker scores are not comparable to the fusion floor). docs section 13/14.
        return AbstentionDecision(abstain=False, reason="", low_confidence=False)

    # no reranker: the scores are fusion scores -> apply the fusion floor + min results
    above_floor = [c for c in candidates if c.score >= abstain_fusion_floor]
    if len(above_floor) < abstain_min_results:
        return AbstentionDecision(abstain=True, reason="low_confidence", low_confidence=False)
    return AbstentionDecision(abstain=False, reason="", low_confidence=False)
