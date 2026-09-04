"""Configuration-driven provider registry (docs/ARCHITECTURE.md section 4.1).

The only module that imports concrete provider classes, and it imports them lazily
so unused providers' dependencies need not be installed. The "no fake providers
outside ci/test" rule is enforced in :func:`app.config.validate_consistency`; the
factories re-assert it as defence in depth.
"""

from __future__ import annotations

from app.config import (
    ConfigError,
    EmbeddingProviderName,
    LLMProviderName,
    RerankerName,
    Settings,
)
from app.core.interfaces.embeddings import EmbeddingProvider
from app.core.interfaces.llm import LLMProvider
from app.core.interfaces.reranker import Reranker


def _forbid_fake(settings: Settings, provider_value: str) -> None:
    if provider_value == "fake" and settings.app_profile.is_runtime:
        raise ConfigError(f"fake provider selected with APP_PROFILE={settings.app_profile.value}")


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    name = settings.embedding_provider
    _forbid_fake(settings, name.value)

    if name is EmbeddingProviderName.FAKE:
        from app.providers.embeddings.fake import FakeEmbedder

        return FakeEmbedder()
    if name is EmbeddingProviderName.FASTEMBED:
        from app.providers.embeddings.fastembed_provider import FastEmbedProvider

        return FastEmbedProvider(settings.embedding_model, max_batch=settings.embedding_max_batch)
    if name is EmbeddingProviderName.OPENAI:
        from app.providers.embeddings.openai_provider import OpenAIEmbeddingProvider

        key = settings.embedding_api_key or settings.llm_api_key
        if key is None:
            raise ConfigError("EMBEDDING_PROVIDER=openai requires EMBEDDING_API_KEY or LLM_API_KEY")
        return OpenAIEmbeddingProvider(
            settings.embedding_model,
            api_key=key.get_secret_value(),
            base_url=settings.embedding_base_url,
            max_batch=settings.embedding_max_batch,
        )
    from app.providers.embeddings.ollama_provider import OllamaEmbeddingProvider

    base = settings.embedding_base_url or settings.llm_base_url
    if not base:
        raise ConfigError("EMBEDDING_PROVIDER=ollama requires EMBEDDING_BASE_URL or LLM_BASE_URL")
    return OllamaEmbeddingProvider(settings.embedding_model, base_url=base)


def build_reranker(settings: Settings) -> Reranker | None:
    name = settings.reranker
    if name is RerankerName.NONE:
        return None
    if name is RerankerName.FASTEMBED_CROSS_ENCODER:
        from app.providers.rerank.fastembed_reranker import FastEmbedReranker

        return FastEmbedReranker(settings.reranker_model)
    key = settings.reranker_api_key
    if key is None:
        raise ConfigError(f"RERANKER={name.value} requires RERANKER_API_KEY")
    if name is RerankerName.COHERE:
        from app.providers.rerank.hosted import CohereReranker

        return CohereReranker(settings.reranker_model, api_key=key.get_secret_value())
    from app.providers.rerank.hosted import JinaReranker

    return JinaReranker(settings.reranker_model, api_key=key.get_secret_value())


def build_llm_provider(settings: Settings, *, fallback: bool = False) -> LLMProvider:
    if fallback:
        name = settings.llm_fallback_provider
        model = settings.llm_fallback_model or settings.llm_model
        api_key = settings.llm_fallback_api_key
    else:
        name = settings.llm_provider
        model = settings.llm_model
        api_key = settings.llm_api_key
    if name is None:
        raise ConfigError("no fallback LLM provider configured")
    _forbid_fake(settings, name.value)
    return _make_llm(settings, name, model, api_key)


def build_eval_judge(settings: Settings) -> LLMProvider:
    name = settings.eval_judge_provider or settings.llm_provider
    model = settings.eval_judge_model or settings.llm_model
    api_key = settings.eval_judge_api_key or settings.llm_api_key
    _forbid_fake(settings, name.value)
    return _make_llm(settings, name, model, api_key)


def _make_llm(
    settings: Settings, name: LLMProviderName, model: str, api_key: object
) -> LLMProvider:
    from pydantic import SecretStr

    secret = api_key.get_secret_value() if isinstance(api_key, SecretStr) else None

    if name is LLMProviderName.FAKE:
        from app.providers.llm.fake import FakeLLM

        return FakeLLM(model_id=model)
    if name is LLMProviderName.OPENAI:
        from app.providers.llm.openai_provider import OpenAIProvider

        if secret is None:
            raise ConfigError("OpenAI provider requires an API key")
        return OpenAIProvider(
            model,
            api_key=secret,
            base_url=settings.llm_base_url,
            timeout_s=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
        )
    if name is LLMProviderName.ANTHROPIC:
        from app.providers.llm.anthropic_provider import AnthropicProvider

        if secret is None:
            raise ConfigError("Anthropic provider requires an API key")
        return AnthropicProvider(
            model,
            api_key=secret,
            timeout_s=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
        )
    from app.providers.llm.ollama_provider import OllamaProvider

    if not settings.llm_base_url:
        raise ConfigError("Ollama provider requires LLM_BASE_URL")
    return OllamaProvider(model, base_url=settings.llm_base_url, timeout_s=settings.llm_timeout_s)
