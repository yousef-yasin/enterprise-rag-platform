"""OpenAI chat adapter (docs/ARCHITECTURE.md section 17)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from functools import cached_property
from typing import Any

from app.core.errors import LLMError, LLMStreamError
from app.core.interfaces.llm import ChatMessage, LLMCapabilities, LLMDelta
from app.core.models import TokenUsage

# context window / max output / price per 1k tokens (USD)
_MODELS: dict[str, tuple[int, int, float, float]] = {
    "gpt-4o-mini": (128_000, 16_384, 0.00015, 0.0006),
    "gpt-4o": (128_000, 16_384, 0.0025, 0.01),
    "gpt-4.1-mini": (1_000_000, 32_768, 0.0004, 0.0016),
    "gpt-4.1": (1_000_000, 32_768, 0.002, 0.008),
    "o4-mini": (200_000, 100_000, 0.0011, 0.0044),
}


class OpenAIProvider:
    def __init__(
        self,
        model_id: str,
        *,
        api_key: str,
        base_url: str | None = None,
        timeout_s: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        cw, mo, ci, co = _MODELS.get(model_id, (128_000, 16_384, 0.001, 0.003))
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
        self._base_url = base_url
        self._timeout = timeout_s
        self._max_retries = max_retries

    @cached_property
    def _client(self) -> Any:
        from openai import AsyncOpenAI

        return AsyncOpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,
            max_retries=self._max_retries,
        )

    @cached_property
    def _encoder(self) -> Any:
        import tiktoken

        try:
            return tiktoken.encoding_for_model(self.caps.model_id)
        except KeyError:
            return tiktoken.get_encoding("o200k_base")

    @staticmethod
    def _to_openai(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stop: Sequence[str] | None = None,
    ) -> AsyncIterator[LLMDelta]:
        kwargs: dict[str, Any] = {
            "model": self.caps.model_id,
            "messages": self._to_openai(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if stop:
            # Omit rather than pass `stop=None`: some OpenAI-compatible endpoints
            # (e.g. Gemini) reject an explicit null for this field.
            kwargs["stop"] = list(stop)
        try:
            stream = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise LLMStreamError(f"OpenAI stream failed to start: {exc}") from exc
        try:
            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                text = choice.delta.content or ""
                if text or choice.finish_reason:
                    yield LLMDelta(text=text, finish_reason=choice.finish_reason)
        except Exception as exc:
            raise LLMStreamError(f"OpenAI stream error: {exc}") from exc

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> tuple[str, TokenUsage]:
        try:
            resp = await self._client.chat.completions.create(
                model=self.caps.model_id,
                messages=self._to_openai(messages),
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            raise LLMError(f"OpenAI completion failed: {exc}") from exc
        usage = resp.usage
        return resp.choices[0].message.content or "", TokenUsage(
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )

    async def complete_structured(
        self,
        messages: Sequence[ChatMessage],
        schema: dict[str, object],
        *,
        temperature: float = 0.0,
    ) -> tuple[dict[str, object], TokenUsage]:
        try:
            resp = await self._client.chat.completions.create(
                model=self.caps.model_id,
                messages=self._to_openai(messages),
                temperature=temperature,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "response", "schema": schema, "strict": True},
                },
            )
        except Exception as exc:
            raise LLMError(f"OpenAI structured completion failed: {exc}") from exc
        usage = resp.usage
        content = resp.choices[0].message.content or "{}"
        parsed: dict[str, object] = json.loads(content)
        return parsed, TokenUsage(
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )

    def count_tokens(self, text: str) -> int:
        return len(self._encoder.encode(text))
