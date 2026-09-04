"""Anthropic chat adapter (docs/ARCHITECTURE.md section 17).

Anthropic takes ``system`` as a top-level parameter, so the adapter extracts it from
the message list. Token counting is best-effort (no exact local tokenizer) — the
budget applies TOKEN_SAFETY_MARGIN.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from functools import cached_property
from typing import Any

from app.core.errors import LLMError, LLMStreamError
from app.core.interfaces.llm import ChatMessage, LLMCapabilities, LLMDelta
from app.core.models import TokenUsage

_MODELS: dict[str, tuple[int, int, float, float]] = {
    "claude-sonnet-5": (200_000, 64_000, 0.003, 0.015),
    "claude-opus-5": (200_000, 64_000, 0.015, 0.075),
    "claude-haiku-4-5-20251001": (200_000, 32_000, 0.001, 0.005),
    "claude-3-5-sonnet-latest": (200_000, 8_192, 0.003, 0.015),
    "claude-3-5-haiku-latest": (200_000, 8_192, 0.0008, 0.004),
}


class AnthropicProvider:
    def __init__(
        self, model_id: str, *, api_key: str, timeout_s: float = 60.0, max_retries: int = 3
    ) -> None:
        cw, mo, ci, co = _MODELS.get(model_id, (200_000, 8_192, 0.003, 0.015))
        self.caps = LLMCapabilities(
            model_id=model_id,
            context_window=cw,
            max_output_tokens=mo,
            supports_streaming=True,
            supports_structured_output=True,
            cost_per_1k_input_usd=ci,
            cost_per_1k_output_usd=co,
        )
        self._api_key = api_key
        self._timeout = timeout_s
        self._max_retries = max_retries

    @cached_property
    def _client(self) -> Any:
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(
            api_key=self._api_key, timeout=self._timeout, max_retries=self._max_retries
        )

    @staticmethod
    def _split(messages: Sequence[ChatMessage]) -> tuple[str, list[dict[str, str]]]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        turns = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        return system, turns

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stop: Sequence[str] | None = None,
    ) -> AsyncIterator[LLMDelta]:
        system, turns = self._split(messages)
        try:
            stream = self._client.messages.stream(
                model=self.caps.model_id,
                system=system or None,
                messages=turns,
                temperature=temperature,
                max_tokens=max_tokens or self.caps.max_output_tokens,
            )
        except Exception as exc:
            raise LLMStreamError(f"Anthropic stream failed to start: {exc}") from exc
        try:
            async with stream as events:
                async for text in events.text_stream:
                    yield LLMDelta(text=text)
            yield LLMDelta(text="", finish_reason="stop")
        except Exception as exc:
            raise LLMStreamError(f"Anthropic stream error: {exc}") from exc

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> tuple[str, TokenUsage]:
        system, turns = self._split(messages)
        try:
            resp = await self._client.messages.create(
                model=self.caps.model_id,
                system=system or None,
                messages=turns,
                temperature=temperature,
                max_tokens=max_tokens or self.caps.max_output_tokens,
            )
        except Exception as exc:
            raise LLMError(f"Anthropic completion failed: {exc}") from exc
        text = "".join(block.text for block in resp.content if block.type == "text")
        return text, TokenUsage(
            prompt_tokens=resp.usage.input_tokens, completion_tokens=resp.usage.output_tokens
        )

    async def complete_structured(
        self,
        messages: Sequence[ChatMessage],
        schema: dict[str, object],
        *,
        temperature: float = 0.0,
    ) -> tuple[dict[str, object], TokenUsage]:
        system, turns = self._split(messages)
        tool = {
            "name": "emit",
            "description": "emit the structured response",
            "input_schema": schema,
        }
        try:
            resp = await self._client.messages.create(
                model=self.caps.model_id,
                system=system or None,
                messages=turns,
                temperature=temperature,
                max_tokens=self.caps.max_output_tokens,
                tools=[tool],
                tool_choice={"type": "tool", "name": "emit"},
            )
        except Exception as exc:
            raise LLMError(f"Anthropic structured completion failed: {exc}") from exc
        for block in resp.content:
            if block.type == "tool_use":
                data: dict[str, object] = dict(block.input)
                return data, TokenUsage(resp.usage.input_tokens, resp.usage.output_tokens)
        raise LLMError("Anthropic returned no structured output")

    def count_tokens(self, text: str) -> int:
        # documented approximation (+/- 10%); the budget applies a safety margin
        return max(1, int(len(text) / 3.6))
