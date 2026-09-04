"""Provider contract suites — fakes (docs/ARCHITECTURE.md section 32).

The same assertions run against real adapters in ``provider-live.yml`` (nightly).
"""

from __future__ import annotations

import math

import pytest

from app.core.embedding_profile import ChunkPolicy, compute_embedding_profile_id
from app.core.interfaces.llm import ChatMessage, LLMProvider
from app.providers.embeddings.fake import FakeEmbedder
from app.providers.llm.fake import FakeLLM


# ── embedding contract ──────────────────────────────────────────────────────
async def test_fake_embedder_dimension_and_normalization() -> None:
    emb = FakeEmbedder()
    vecs = await emb.embed_documents(["hello world", "another passage"])
    assert all(len(v) == emb.profile.dimension for v in vecs)
    for v in vecs:
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6)


async def test_fake_embedder_query_doc_asymmetry() -> None:
    emb = FakeEmbedder()
    q = await emb.embed_query("penalty clause")
    d = (await emb.embed_documents(["penalty clause"]))[0]
    assert q != d  # prefixes differ (section 16.2)


def test_fake_embedder_profile_id_stable_and_policy_sensitive() -> None:
    emb = FakeEmbedder()
    policy = ChunkPolicy(0.8, 0.15, 512, True, "{title}")
    a = compute_embedding_profile_id(emb.profile, policy)
    b = compute_embedding_profile_id(emb.profile, policy)
    changed = compute_embedding_profile_id(emb.profile, ChunkPolicy(0.8, 0.5, 512, True, "{title}"))
    assert a == b != changed


def test_fake_embedder_count_tokens_monotonic() -> None:
    emb = FakeEmbedder()
    assert emb.count_tokens("a b c d") <= emb.count_tokens("a b c d e f g h")


# ── LLM contract ────────────────────────────────────────────────────────────
_CTX = "<<CONTEXT 1>> (source: h.md)\nHealth insurance is included in the plan.\n<</CONTEXT 1>>"


@pytest.fixture
def llm() -> LLMProvider:
    return FakeLLM()


async def test_fake_llm_caps(llm: LLMProvider) -> None:
    assert llm.caps.context_window > 0
    assert llm.caps.supports_streaming
    assert llm.caps.supports_structured_output


async def test_fake_llm_streams_and_completes(llm: LLMProvider) -> None:
    msgs = [ChatMessage(role="user", content=f"{_CTX}\n\nQuestion: what is covered?")]
    streamed = "".join([d.text async for d in llm.generate(msgs)])
    assert "[[1]]" in streamed

    text, usage = await llm.complete(msgs)
    assert "[[1]]" in text
    assert usage.prompt_tokens > 0


async def test_fake_llm_refuses_without_context(llm: LLMProvider) -> None:
    text, _u = await llm.complete(
        [ChatMessage(role="user", content="what is the capital of Mars?")]
    )
    assert "could not find" in text.lower()


async def test_fake_llm_structured_output(llm: LLMProvider) -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"score": {"type": "number"}, "supported": {"type": "boolean"}},
    }
    obj, _u = await llm.complete_structured([ChatMessage(role="user", content="rate this")], schema)
    assert set(obj) == {"score", "supported"}
