"""Ollama chat adapter (local, docs/ARCHITECTURE.md section 17)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence

import httpx

from app.core.errors import LLMError, LLMStreamError
from app.core.interfaces.llm import ChatMessage, LLMCapabilities, LLMDelta
from app.core.models import TokenUsage

_CONTEXT_WINDOWS = {"llama3.2:3b": 128_000, "llama3.1:8b": 128_000, "qwen2.5:7b": 32_768}


class OllamaProvider:
    def __init__(self, model_id: str, *, base_url: str, timeout_s: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        self.caps = LLMCapabilities(
            model_id=model_id,
            context_window=_CONTEXT_WINDOWS.get(model_id, 8192),
            max_output_tokens=4096,
            supports_streaming=True,
            supports_structured_output=True,
            cost_per_1k_input_usd=0.0,
            cost_per_1k_output_usd=0.0,
        )

    def _messages(self, messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stop: Sequence[str] | None = None,
    ) -> AsyncIterator[LLMDelta]:
        payload = {
            "model": self.caps.model_id,
            "messages": self._messages(messages),
            "stream": True,
            "options": {"temperature": temperature},
        }
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout) as client,
                client.stream("POST", f"{self._base_url}/api/chat", json=payload) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    text = data.get("message", {}).get("content", "")
                    done = data.get("done", False)
                    if text or done:
                        yield LLMDelta(text=text, finish_reason="stop" if done else None)
        except Exception as exc:
            raise LLMStreamError(f"Ollama stream error: {exc}") from exc

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> tuple[str, TokenUsage]:
        payload = {
            "model": self.caps.model_id,
            "messages": self._messages(messages),
            "stream": False,
            "options": {"temperature": temperature},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f"{self._base_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise LLMError(f"Ollama completion failed: {exc}") from exc
        text = data.get("message", {}).get("content", "")
        return text, TokenUsage(
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
        )

    async def complete_structured(
        self,
        messages: Sequence[ChatMessage],
        schema: dict[str, object],
        *,
        temperature: float = 0.0,
    ) -> tuple[dict[str, object], TokenUsage]:
        payload = {
            "model": self.caps.model_id,
            "messages": self._messages(messages),
            "stream": False,
            "format": schema,
            "options": {"temperature": temperature},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f"{self._base_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise LLMError(f"Ollama structured completion failed: {exc}") from exc
        content = data.get("message", {}).get("content", "{}")
        parsed: dict[str, object] = json.loads(content)
        return parsed, TokenUsage(
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)
