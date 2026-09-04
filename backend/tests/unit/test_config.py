"""Configuration loading and validation (docs/ARCHITECTURE.md §26, Phase 0 gate)."""

from __future__ import annotations

import pytest

from app.config import (
    AppProfile,
    ConfigError,
    Settings,
    get_settings,
    validate_consistency,
)


def _settings(**overrides: object) -> Settings:
    """Build Settings from explicit values (init kwargs beat env in pydantic-settings)."""
    base: dict[str, object] = {
        "app_profile": "local",
        "llm_provider": "openai",
        "embedding_provider": "fastembed",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_defaults_load_in_test_profile() -> None:
    settings = get_settings()
    assert settings.app_profile is AppProfile.TEST
    assert settings.llm_provider.value == "fake"
    assert settings.embedding_provider.value == "fake"


def test_hosted_llm_without_api_key_is_rejected() -> None:
    settings = _settings(llm_provider="openai", llm_api_key=None)
    with pytest.raises(ConfigError) as excinfo:
        validate_consistency(settings)
    message = str(excinfo.value)
    assert "LLM_API_KEY" in message
    assert "docker compose --profile local up" in message


def test_hosted_llm_with_api_key_is_accepted() -> None:
    validate_consistency(_settings(llm_provider="anthropic", llm_api_key="sk-test"))


def test_fake_llm_forbidden_in_runtime_profile() -> None:
    with pytest.raises(ConfigError, match="ci or APP_PROFILE=test"):
        validate_consistency(_settings(app_profile="local", llm_provider="fake"))


def test_fake_embedding_forbidden_in_prod_profile() -> None:
    with pytest.raises(ConfigError, match="EMBEDDING_PROVIDER"):
        validate_consistency(
            _settings(
                app_profile="prod",
                llm_provider="openai",
                llm_api_key="k",
                embedding_provider="fake",
            )
        )


def test_fake_providers_allowed_in_ci_profile() -> None:
    validate_consistency(
        _settings(app_profile="ci", llm_provider="fake", embedding_provider="fake")
    )


def test_ollama_requires_base_url() -> None:
    with pytest.raises(ConfigError, match="LLM_BASE_URL"):
        validate_consistency(_settings(llm_provider="ollama", llm_base_url=None))
    validate_consistency(_settings(llm_provider="ollama", llm_base_url="http://ollama:11434"))


def test_embedding_fallback_env_is_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_FALLBACK_PROVIDER", "openai")
    with pytest.raises(ConfigError, match="fallback is forbidden"):
        validate_consistency(_settings(llm_provider="openai", llm_api_key="k"))


def test_multiple_problems_reported_together() -> None:
    with pytest.raises(ConfigError) as excinfo:
        validate_consistency(
            _settings(app_profile="local", llm_provider="fake", embedding_provider="fake")
        )
    # fake LLM + fake embedding, both surfaced in one message.
    assert "2 problem(s)" in str(excinfo.value)
    assert "LLM_PROVIDER" in str(excinfo.value)
    assert "EMBEDDING_PROVIDER" in str(excinfo.value)


def test_get_settings_wraps_bad_values_as_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_PORT", "not-a-number")
    get_settings.cache_clear()
    with pytest.raises(ConfigError):
        get_settings()


def test_invalid_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_LOG_LEVEL", "LOUD")
    get_settings.cache_clear()
    with pytest.raises(ConfigError):
        get_settings()


def test_cors_origins_parsed_from_csv() -> None:
    settings = _settings(
        llm_provider="openai",
        llm_api_key="k",
        cors_allow_origins="http://a ,http://b, ",
    )
    assert settings.cors_origins == ["http://a", "http://b"]


def test_secrets_are_not_rendered() -> None:
    settings = _settings(llm_provider="openai", llm_api_key="super-secret-value")
    assert "super-secret-value" not in repr(settings)
    assert "rag_local_dev" not in repr(settings)
    summary = settings.safe_summary()
    assert summary["llm_key_configured"] is True
    assert "super-secret-value" not in str(summary)
