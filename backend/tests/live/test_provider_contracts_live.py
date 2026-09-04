"""Live hosted-provider contract checks (docs/ARCHITECTURE.md §17, §34).

Only run by the `provider-live` workflow (or manually):

    RAG_LIVE_PROVIDERS=1 OPENAI_API_KEY=... uv run pytest -m live

These make real, billable API calls. They assert the adapter honours the
``LLMProvider`` contract — streaming, non-streaming, structured output, token
counting — not answer quality.
"""

from __future__ import annotations

import os

import pytest

from app.core.interfaces.llm import ChatMessage

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RAG_LIVE_PROVIDERS") != "1",
        reason="live provider tests are opt-in (RAG_LIVE_PROVIDERS=1)",
    ),
]

_CASES: list[tuple[str, str, str]] = []
if os.environ.get("OPENAI_API_KEY"):
    _CASES.append(("openai", "gpt-4o-mini", "OPENAI_API_KEY"))
if os.environ.get("ANTHROPIC_API_KEY"):
    _CASES.append(("anthropic", "claude-3-5-haiku-latest", "ANTHROPIC_API_KEY"))

_PARAMS: list[object] = list(_CASES) or [
    pytest.param(("", "", ""), marks=pytest.mark.skip(reason="no provider keys configured"))
]


@pytest.fixture(params=_PARAMS)
def provider(request: pytest.FixtureRequest):  # type: ignore[no-untyped-def]
    from app.config import get_settings
    from app.providers.registry import build_llm_provider

    name, model, env_key = request.param
    monkey = request.getfixturevalue("monkeypatch")
    monkey.setenv("APP_PROFILE", "local")
    monkey.setenv("LLM_PROVIDER", name)
    monkey.setenv("LLM_MODEL", model)
    monkey.setenv("LLM_API_KEY", os.environ[env_key])
    monkey.setenv("EMBEDDING_PROVIDER", "fastembed")
    get_settings.cache_clear()
    return build_llm_provider(get_settings())


async def test_stream_and_complete(provider) -> None:  # type: ignore[no-untyped-def]
    msgs = [ChatMessage(role="user", content="Reply with exactly the word: pong")]

    chunks = [d.text async for d in provider.generate(msgs, max_tokens=16)]
    assert "".join(chunks).strip()

    text, usage = await provider.complete(msgs, max_tokens=16)
    assert text.strip()
    assert usage.prompt_tokens > 0
    assert provider.count_tokens("hello world") >= 1


async def test_structured_output(provider) -> None:  # type: ignore[no-untyped-def]
    schema = {
        "type": "object",
        "properties": {"sentiment": {"type": "string"}, "score": {"type": "number"}},
        "required": ["sentiment", "score"],
    }
    obj, _usage = await provider.complete_structured(
        [ChatMessage(role="user", content="Classify: 'I love this'. Return the JSON.")],
        schema,
    )
    assert set(obj) >= {"sentiment", "score"}
