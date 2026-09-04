"""Retrieval / answer / citation / abstention metrics (docs/ARCHITECTURE.md §33.2).

Every function is pure and operates on a single sample. Aggregation and CIs are
handled by :mod:`app.core.eval.bootstrap`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


# ── retrieval ───────────────────────────────────────────────────────────────
def _dedupe(seq: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def recall_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    rel = set(relevant)
    if not rel:
        return math.nan
    top = set(_dedupe(retrieved)[:k])
    return len(top & rel) / len(rel)


def precision_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    if k <= 0:
        return math.nan
    rel = set(relevant)
    top = _dedupe(retrieved)[:k]
    if not top:
        return 0.0
    return sum(1 for x in top if x in rel) / len(top)


def hit_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    rel = set(relevant)
    return 1.0 if rel & set(_dedupe(retrieved)[:k]) else 0.0


def reciprocal_rank(retrieved: Sequence[str], relevant: Sequence[str]) -> float:
    rel = set(relevant)
    for i, x in enumerate(_dedupe(retrieved), start=1):
        if x in rel:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    rel = set(relevant)
    if not rel:
        return math.nan
    top = _dedupe(retrieved)[:k]
    dcg = sum(1.0 / math.log2(i + 1) for i, x in enumerate(top, start=1) if x in rel)
    ideal_hits = min(len(rel), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


# ── citations ───────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class CitationScore:
    precision: float
    recall: float
    cited_in_context: float  # hard gate: 1.0 iff every cited chunk was in context


def citation_score(
    cited_chunk_ids: Sequence[str],
    context_chunk_ids: Sequence[str],
    supporting_chunk_ids: Sequence[str] | None = None,
) -> CitationScore:
    """`supporting_chunk_ids` — the gold chunks that actually answer the question
    (falls back to the retrieved context when the dataset does not label them)."""
    cited = set(cited_chunk_ids)
    context = set(context_chunk_ids)
    support = set(supporting_chunk_ids) if supporting_chunk_ids else context

    in_context = 1.0 if cited <= context else 0.0
    precision = len(cited & support) / len(cited) if cited else math.nan
    recall = len(cited & support) / len(support) if support else math.nan
    return CitationScore(precision=precision, recall=recall, cited_in_context=in_context)


# ── abstention ──────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class AbstentionOutcome:
    """One sample's contribution to abstention precision / recall.

    tp — should abstain and did;  fp — should not abstain but did;
    fn — should abstain but did not;  tn — should not abstain and did not.
    """

    tp: int
    fp: int
    fn: int
    tn: int


def abstention_outcome(*, should_abstain: bool, did_abstain: bool) -> AbstentionOutcome:
    return AbstentionOutcome(
        tp=int(should_abstain and did_abstain),
        fp=int(not should_abstain and did_abstain),
        fn=int(should_abstain and not did_abstain),
        tn=int(not should_abstain and not did_abstain),
    )


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else math.nan
    recall = tp / (tp + fn) if (tp + fn) else math.nan
    if precision != precision or recall != recall or (precision + recall) == 0:
        return precision, recall, math.nan
    f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


# ── answer text ─────────────────────────────────────────────────────────────
def token_f1(prediction: str, reference: str) -> float:
    """Bag-of-words F1 — a cheap, judge-independent floor for answer correctness."""
    pred = _norm_tokens(prediction)
    ref = _norm_tokens(reference)
    if not pred and not ref:
        return 1.0
    if not pred or not ref:
        return 0.0
    common: dict[str, int] = {}
    ref_counts = _counts(ref)
    pred_counts = _counts(pred)
    for tok, c in pred_counts.items():
        if tok in ref_counts:
            common[tok] = min(c, ref_counts[tok])
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred)
    recall = overlap / len(ref)
    return 2 * precision * recall / (precision + recall)


def _norm_tokens(text: str) -> list[str]:
    keep = []
    for raw in text.lower().split():
        tok = "".join(ch for ch in raw if ch.isalnum())
        if tok and tok not in _STOP:
            keep.append(tok)
    return keep


def _counts(tokens: Sequence[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in tokens:
        out[t] = out.get(t, 0) + 1
    return out


_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "and",
        "or",
        "not",
        "no",
        "as",
        "by",
        "with",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "from",
        "into",
    ]
)
