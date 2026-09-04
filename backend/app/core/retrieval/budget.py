"""Token-budget-aware context assembly (docs/ARCHITECTURE.md section 15)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.core.models import ScoredChunk

TokenCounter = Callable[[str], int]


@dataclass(frozen=True, slots=True)
class ContextBlock:
    citation_index: int
    chunk_id: str
    document_id: str
    filename: str
    page_no: int | None
    text: str


@dataclass(frozen=True, slots=True)
class BudgetInputs:
    context_window: int
    max_output_tokens: int
    system_tokens: int
    question_tokens: int
    safety_margin: float
    response_headroom_tokens: int
    context_budget_share: float


@dataclass(frozen=True, slots=True)
class AssembledContext:
    blocks: tuple[ContextBlock, ...]
    history_token_budget: int
    citation_map: dict[int, tuple[str, str]]


def assemble_context(
    reranked: Sequence[ScoredChunk],
    *,
    inputs: BudgetInputs,
    count_tokens: TokenCounter,
    expand: Callable[[ScoredChunk], str],
) -> AssembledContext:
    budget_total = int(inputs.context_window * inputs.safety_margin)
    reserve_output = max(inputs.max_output_tokens, inputs.response_headroom_tokens)
    budget_for_prompt = (
        budget_total - reserve_output - inputs.system_tokens - inputs.question_tokens
    )
    budget_for_prompt = max(budget_for_prompt, 0)
    context_budget = int(budget_for_prompt * inputs.context_budget_share)

    blocks: list[ContextBlock] = []
    citation_map: dict[int, tuple[str, str]] = {}
    used = 0
    for chunk in reranked:
        text = expand(chunk)
        block_tokens = count_tokens(text)
        if blocks and used + block_tokens > context_budget:
            break
        if not blocks and block_tokens > context_budget:
            text = _truncate(text, context_budget, count_tokens)
            block_tokens = count_tokens(text)
        idx = len(blocks) + 1
        blocks.append(
            ContextBlock(
                citation_index=idx,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                filename=chunk.filename,
                page_no=chunk.page_no,
                text=text,
            )
        )
        citation_map[idx] = (chunk.chunk_id, chunk.document_id)
        used += block_tokens
        if not reranked:
            break

    history_budget = max(budget_for_prompt - used, 0)
    return AssembledContext(
        blocks=tuple(blocks),
        history_token_budget=history_budget,
        citation_map=citation_map,
    )


def _truncate(text: str, budget: int, count_tokens: TokenCounter) -> str:
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_tokens(text[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip()


def trim_history(
    turns: Sequence[tuple[str, str]], *, budget: int, count_tokens: TokenCounter
) -> list[tuple[str, str]]:
    """``turns`` newest-last; keep as many recent turns as fit (docs/ARCHITECTURE.md section 15)."""

    kept: list[tuple[str, str]] = []
    used = 0
    for role, content in reversed(turns):
        t = count_tokens(content)
        if used + t > budget and kept:
            break
        kept.insert(0, (role, content))
        used += t
    return kept
