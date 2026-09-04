"""Deterministic fake LLM (tests / CI only, docs/ARCHITECTURE.md section 16.4/17)."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Sequence

from app.core.interfaces.llm import ChatMessage, LLMCapabilities, LLMDelta
from app.core.models import TokenUsage

_CONTEXT = re.compile(r"<<CONTEXT (\d+)>>\s*(.*?)\s*<</CONTEXT \1>>", re.DOTALL)


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class FakeLLM:
    def __init__(self, model_id: str = "fake-llm") -> None:
        self.caps = LLMCapabilities(
            model_id=model_id,
            context_window=8192,
            max_output_tokens=1024,
            supports_streaming=True,
            supports_structured_output=True,
            cost_per_1k_input_usd=0.0,
            cost_per_1k_output_usd=0.0,
        )

    def _answer(self, messages: Sequence[ChatMessage]) -> str:
        system = " ".join(m.content for m in messages if m.role == "system")
        joined = "\n".join(m.content for m in messages)

        # query-rewrite prompt (section 7): echo the latest user line as a standalone query
        if "standalone search query" in system:
            user_lines = [
                line[6:].strip()
                for m in messages
                if m.role == "user"
                for line in m.content.splitlines()
                if line.startswith("user: ")
            ]
            return user_lines[-1] if user_lines else messages[-1].content.strip()

        # eval-judge / structured prompts are handled by complete_structured
        blocks = _CONTEXT.findall(joined)
        if not blocks:
            return "I could not find information about that in the knowledge base."
        first = blocks[0][1].strip().split("\n")[-1][:240]
        parts = [f"Based on the provided context: {first} [[1]]"]
        if len(blocks) > 1:
            parts.append("Additional detail is available [[2]].")
        return " ".join(parts)

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stop: Sequence[str] | None = None,
    ) -> AsyncIterator[LLMDelta]:
        answer = self._answer(messages)
        for token in answer.split(" "):
            yield LLMDelta(text=token + " ")
        yield LLMDelta(text="", finish_reason="stop")

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> tuple[str, TokenUsage]:
        answer = self._answer(messages)
        prompt_tokens = sum(_approx_tokens(m.content) for m in messages)
        return answer, TokenUsage(prompt_tokens, _approx_tokens(answer))

    async def complete_structured(
        self,
        messages: Sequence[ChatMessage],
        schema: dict[str, object],
        *,
        temperature: float = 0.0,
    ) -> tuple[dict[str, object], TokenUsage]:
        props = schema.get("properties", {})
        obj: dict[str, object] = {}
        items = props.items() if isinstance(props, dict) else []
        for key, spec in items:
            kind = spec.get("type") if isinstance(spec, dict) else "string"
            if kind == "number":
                obj[key] = 0.7
            elif kind == "integer":
                obj[key] = 1
            elif kind == "boolean":
                obj[key] = True
            elif kind == "array":
                obj[key] = []
            else:
                obj[key] = "fake"
        prompt_tokens = sum(_approx_tokens(m.content) for m in messages)
        return obj, TokenUsage(prompt_tokens, _approx_tokens(json.dumps(obj)))

    def count_tokens(self, text: str) -> int:
        return _approx_tokens(text)
