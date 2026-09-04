"""LLM provider abstraction (docs/ARCHITECTURE.md §17). Adapters land in Phase 6."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from app.core.models import TokenUsage

Role = Literal["system", "user", "assistant"]


class NotSupportedError(RuntimeError):
    """Raised by an adapter for an optional capability it does not implement
    (for example ``complete_structured`` on a model without JSON/tool support)."""


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class LLMDelta:
    """One streamed chunk of a generation."""

    text: str
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class LLMCapabilities:
    """Static provider metadata used by the token-budget algorithm (§15) and cost
    tracking (§28.3)."""

    model_id: str
    context_window: int
    max_output_tokens: int
    supports_streaming: bool
    supports_structured_output: bool
    cost_per_1k_input_usd: float | None = None
    cost_per_1k_output_usd: float | None = None


@runtime_checkable
class LLMProvider(Protocol):
    caps: LLMCapabilities

    def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stop: Sequence[str] | None = None,
    ) -> AsyncIterator[LLMDelta]:
        """Stream a completion. Streaming-failure semantics: §17.3."""
        ...

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> tuple[str, TokenUsage]:
        """Non-streaming completion (used by query rewriting and the eval judge)."""
        ...

    async def complete_structured(
        self,
        messages: Sequence[ChatMessage],
        schema: dict[str, object],
        *,
        temperature: float = 0.0,
    ) -> tuple[dict[str, object], TokenUsage]:
        """JSON-schema-constrained completion. Raises :class:`NotSupportedError` when the
        adapter cannot honour the schema."""
        ...

    def count_tokens(self, text: str) -> int:
        """Best-effort token count. Exact where a local tokenizer exists, otherwise
        approximate (±10%); the token budget applies a safety margin (§17.2)."""
        ...
