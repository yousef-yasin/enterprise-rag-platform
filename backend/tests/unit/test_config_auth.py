"""Phase 1 config validation additions (docs/ARCHITECTURE.md §25.2)."""

from __future__ import annotations

import pytest

from app.config import ConfigError, Settings, validate_consistency


def _s(**kw: object) -> Settings:
    base: dict[str, object] = {
        "app_profile": "local",
        "llm_provider": "openai",
        "llm_api_key": "k",
        "embedding_provider": "fastembed",
    }
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


def test_single_user_mode_requires_loopback_bind() -> None:
    with pytest.raises(ConfigError, match="loopback BIND_HOST"):
        validate_consistency(_s(auth_mode="single_user", bind_host="0.0.0.0"))
    validate_consistency(_s(auth_mode="single_user", bind_host="127.0.0.1"))
    validate_consistency(_s(auth_mode="single_user", bind_host="localhost"))


def test_prod_requires_strong_jwt_secret() -> None:
    with pytest.raises(ConfigError, match="JWT_SECRET"):
        validate_consistency(_s(app_profile="prod", session_cookie_secure=True))
    validate_consistency(_s(app_profile="prod", jwt_secret="x" * 40, session_cookie_secure=True))


def test_prod_requires_secure_session_cookie() -> None:
    with pytest.raises(ConfigError, match="SESSION_COOKIE_SECURE"):
        validate_consistency(_s(app_profile="prod", jwt_secret="x" * 40))
    validate_consistency(_s(app_profile="prod", jwt_secret="x" * 40, session_cookie_secure=True))


def test_samesite_none_requires_secure() -> None:
    with pytest.raises(ConfigError, match="SESSION_COOKIE_SAMESITE=none"):
        validate_consistency(_s(session_cookie_samesite="none"))
    validate_consistency(_s(session_cookie_samesite="none", session_cookie_secure=True))


def test_hosted_fallback_provider_requires_key() -> None:
    with pytest.raises(ConfigError, match="LLM_FALLBACK_API_KEY"):
        validate_consistency(_s(llm_fallback_provider="anthropic"))
    validate_consistency(_s(llm_fallback_provider="anthropic", llm_fallback_api_key="k2"))


def test_s3_backend_requires_bucket() -> None:
    with pytest.raises(ConfigError, match="S3_BUCKET"):
        validate_consistency(_s(storage_backend="s3"))


def test_retrieval_nested_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RETRIEVAL__DENSE_TOP_K", "17")
    monkeypatch.setenv("RETRIEVAL__FUSION_STRATEGY", "dbsf")
    settings = _s()
    assert settings.retrieval.dense_top_k == 17
    assert settings.retrieval.fusion_strategy.value == "dbsf"


def test_redacted_config_excludes_secrets() -> None:
    settings = _s(llm_api_key="super-secret", jwt_secret="also-secret-value-thirty-two-chars-x")
    redacted = settings.redacted_config()
    assert "super-secret" not in str(redacted)
    assert "also-secret" not in str(redacted)
    assert redacted["llm_provider"] == "openai"
    assert "retrieval" in redacted
