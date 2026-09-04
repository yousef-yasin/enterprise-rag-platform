"""Follow-up query contextualization (docs/ARCHITECTURE.md section 7)."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.interfaces.llm import ChatMessage

_SYSTEM = (
    "Rewrite the user's latest message as a single standalone search query that makes "
    "sense without the conversation history. Preserve named entities and specifics. "
    "Do NOT answer the question. Respond with only the rewritten query."
)


def build_rewrite_messages(
    latest: str, history: Sequence[tuple[str, str]], *, max_turns: int
) -> list[ChatMessage]:
    recent = list(history)[-max_turns * 2 :]
    lines = [f"{role}: {content}" for role, content in recent]
    lines.append(f"user: {latest}")
    return [
        ChatMessage(role="system", content=_SYSTEM),
        ChatMessage(role="user", content="\n".join(lines)),
    ]


def clean_rewrite(raw: str, fallback: str) -> str:
    text = raw.strip().strip('"').strip()
    first_line = text.splitlines()[0].strip() if text else ""
    if not first_line or len(first_line) > 500:
        return fallback
    return first_line
