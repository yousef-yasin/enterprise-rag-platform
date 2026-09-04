"""Fusion, dedup, token budget, citations, abstention (docs/ARCHITECTURE.md 12-14, 15, 18)."""

from __future__ import annotations

from app.core.citations import parse_and_validate
from app.core.enums import FusionStrategy
from app.core.models import ScoredChunk
from app.core.retrieval.abstention import decide
from app.core.retrieval.budget import BudgetInputs, assemble_context, trim_history
from app.core.retrieval.dedup import suppress_duplicates
from app.core.retrieval.fusion import Ranked, fuse, reciprocal_rank_fusion


# ── fusion ──────────────────────────────────────────────────────────────────
def test_rrf_known_lists() -> None:
    dense = [Ranked("a", 0.9), Ranked("b", 0.8), Ranked("c", 0.1)]
    sparse = [Ranked("b", 5.0), Ranked("d", 3.0), Ranked("a", 1.0)]
    fused = reciprocal_rank_fusion(dense, sparse, k=60)
    # b appears high in both -> should win
    assert fused[0].id == "b"
    assert {r.id for r in fused} == {"a", "b", "c", "d"}


def test_fuse_degrades_to_single_list() -> None:
    dense = [Ranked("a", 1.0), Ranked("b", 0.5)]
    assert [
        r.id
        for r in fuse(
            dense,
            [],
            strategy=FusionStrategy.RRF,
            rrf_k=60,
            dense_weight=1,
            sparse_weight=1,
            limit=10,
        )
    ] == ["a", "b"]


def test_dbsf_and_weighted_norm_run() -> None:
    dense = [Ranked("a", 0.9), Ranked("b", 0.2)]
    sparse = [Ranked("b", 8.0), Ranked("a", 1.0)]
    for strat in (FusionStrategy.DBSF, FusionStrategy.WEIGHTED_NORM):
        out = fuse(
            dense, sparse, strategy=strat, rrf_k=60, dense_weight=1, sparse_weight=1, limit=5
        )
        assert {r.id for r in out} == {"a", "b"}


# ── dedup ───────────────────────────────────────────────────────────────────
def test_dedup_removes_identical_text() -> None:
    chunks = [
        ScoredChunk("1", "d", 0.9, content="Health insurance is included."),
        ScoredChunk("2", "d", 0.8, content="health insurance IS   included."),
        ScoredChunk("3", "d", 0.7, content="A totally different clause."),
    ]
    kept = suppress_duplicates(chunks, cosine_threshold=0.97)
    assert [c.chunk_id for c in kept] == ["1", "3"]


def test_dedup_removes_near_duplicate_by_vector() -> None:
    v = (1.0, 0.0, 0.0)
    chunks = [
        ScoredChunk("1", "d", 0.9, content="x", dense=v),
        ScoredChunk("2", "d", 0.8, content="y", dense=(0.999, 0.001, 0.0)),
    ]
    assert len(suppress_duplicates(chunks, cosine_threshold=0.97)) == 1


# ── token budget ────────────────────────────────────────────────────────────
def _count(text: str) -> int:
    return max(1, len(text.split()))


def test_context_assembly_respects_budget_and_keeps_one() -> None:
    chunks = [ScoredChunk(str(i), "d", 1.0 - i / 10, content=("word " * 50)) for i in range(6)]
    inputs = BudgetInputs(
        context_window=200,
        max_output_tokens=20,
        system_tokens=10,
        question_tokens=5,
        safety_margin=0.9,
        response_headroom_tokens=20,
        context_budget_share=0.7,
    )
    assembled = assemble_context(
        chunks, inputs=inputs, count_tokens=_count, expand=lambda c: c.content
    )
    assert len(assembled.blocks) >= 1
    total = sum(_count(b.text) for b in assembled.blocks)
    budget = int(int(200 * 0.9 - 20 - 10 - 5) * 0.7)
    assert total <= budget or len(assembled.blocks) == 1
    assert list(assembled.citation_map) == [b.citation_index for b in assembled.blocks]


def test_trim_history_keeps_newest() -> None:
    turns = [("user", "a " * 10), ("assistant", "b " * 10), ("user", "c " * 10)]
    kept = trim_history(turns, budget=12, count_tokens=_count)
    assert kept[-1][1].startswith("c")
    assert len(kept) < 3


# ── citations ───────────────────────────────────────────────────────────────
def test_citation_strips_out_of_range_markers() -> None:
    cmap = {1: ("c1", "d1"), 2: ("c2", "d1")}
    result = parse_and_validate("Fact one [[1]]. Fact two [[5]]. Fact three [[2]].", cmap)
    assert "[[5]]" not in result.text
    assert result.invalid_markers == 1
    by_idx = {r.citation_index: r for r in result.records}
    assert by_idx[1].was_cited and by_idx[2].was_cited


def test_citation_flags_uncited_sentence() -> None:
    cmap = {1: ("c1", "d1")}
    result = parse_and_validate(
        "The company was founded in 1998 and grew rapidly across markets. Revenue is high [[1]].",
        cmap,
    )
    assert any("founded in 1998" in s for s in result.uncited_sentences)


def test_citation_weak_flag() -> None:
    cmap = {1: ("c1", "d1")}
    result = parse_and_validate("Something [[1]].", cmap, weak_sentences={1})
    assert result.records[0].weak is True


# ── abstention ──────────────────────────────────────────────────────────────
def test_abstain_on_empty_kb() -> None:
    d = decide(
        [],
        kb_is_empty=True,
        abstain_on_empty=True,
        reranker_model=None,
        abstain_min_results=1,
        abstain_fusion_floor=0.0,
        low_confidence_margin=0.05,
    )
    assert d.abstain and d.reason == "empty_kb"


def test_abstain_on_no_results() -> None:
    d = decide(
        [],
        kb_is_empty=False,
        abstain_on_empty=True,
        reranker_model=None,
        abstain_min_results=1,
        abstain_fusion_floor=0.0,
        low_confidence_margin=0.05,
    )
    assert d.abstain and d.reason == "no_results"


def test_no_abstain_with_results_uncalibrated() -> None:
    chunks = [ScoredChunk("1", "d", 0.5, content="x")]
    d = decide(
        chunks,
        kb_is_empty=False,
        abstain_on_empty=True,
        reranker_model=None,
        abstain_min_results=1,
        abstain_fusion_floor=0.0,
        low_confidence_margin=0.05,
    )
    assert not d.abstain
