"""Typed application configuration (docs/ARCHITECTURE.md §26).

Single source of truth for settings. Everything reads :func:`get_settings`; nothing
else in the codebase touches ``os.environ``. Invalid configuration raises
:class:`ConfigError` with a message intended for a human operator — the API and the
``rag`` CLI both surface it and exit non-zero (fail-fast, §2).
"""

from __future__ import annotations

import ipaddress
import os
from enum import StrEnum
from functools import lru_cache

from pydantic import BaseModel, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import FusionStrategy


class ConfigError(RuntimeError):
    """Configuration is invalid. The message is safe to show to an operator."""


class AppProfile(StrEnum):
    LOCAL = "local"
    PROD = "prod"
    CI = "ci"
    TEST = "test"

    @property
    def is_runtime(self) -> bool:
        return self in (AppProfile.LOCAL, AppProfile.PROD)


class LLMProviderName(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    FAKE = "fake"


class EmbeddingProviderName(StrEnum):
    FASTEMBED = "fastembed"
    OPENAI = "openai"
    OLLAMA = "ollama"
    FAKE = "fake"


class RerankerName(StrEnum):
    FASTEMBED_CROSS_ENCODER = "fastembed_cross_encoder"
    COHERE = "cohere"
    JINA = "jina"
    NONE = "none"


class AuthMode(StrEnum):
    MULTI_USER = "multi_user"
    SINGLE_USER = "single_user"


class StorageBackend(StrEnum):
    LOCAL = "local"
    S3 = "s3"


HOSTED_LLM_PROVIDERS: frozenset[LLMProviderName] = frozenset(
    {LLMProviderName.OPENAI, LLMProviderName.ANTHROPIC}
)
FAKE_LLM_PROVIDERS: frozenset[LLMProviderName] = frozenset({LLMProviderName.FAKE})
FAKE_EMBEDDING_PROVIDERS: frozenset[EmbeddingProviderName] = frozenset({EmbeddingProviderName.FAKE})


class RetrievalSettings(BaseModel):
    """RETRIEVAL__* — the retrieval-pipeline tuning surface (docs/ARCHITECTURE.md §6)."""

    query_rewrite_enabled: bool = True
    query_rewrite_timeout_ms: int = 3000
    query_rewrite_history_turns: int = 6

    embed_cache_ttl: int = 3600
    embed_doc_cache_ttl: int = 86400
    ret_cache_ttl: int = 60

    dense_top_k: int = 40
    sparse_top_k: int = 40

    fusion_strategy: FusionStrategy = FusionStrategy.RRF
    rrf_k: int = 60
    fusion_top_k: int = 24
    hybrid_dense_weight: float = 1.0
    hybrid_sparse_weight: float = 1.0

    dedup_cosine: float = 0.97

    rerank_input_k: int = 12
    rerank_output_k: int = 6
    rerank_timeout_ms: int = 4000

    abstain_on_empty: bool = True
    abstain_min_results: int = 1
    abstain_fusion_floor: float = 0.0
    low_confidence_margin: float = 0.05

    citation_sim_warn: float = 0.35

    context_expansion_tokens: int = 250
    response_headroom_tokens: int = 1024
    context_budget_share: float = 0.7
    token_safety_margin: float = 0.9

    hybrid_enabled: bool = True


class Settings(BaseSettings):
    """Effective configuration. Immutable; build via :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_file=None,
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # ── App ────────────────────────────────────────────────────────────────
    app_profile: AppProfile = AppProfile.LOCAL
    app_name: str = "enterprise-rag-platform"
    app_version: str = "0.0.0"
    app_log_level: str = "INFO"
    app_log_json: bool = True
    bind_host: str = "127.0.0.1"
    prompt_version: str = "v1"

    # ── Auth (docs/ARCHITECTURE.md §25) ───────────────────────────────────
    auth_mode: AuthMode = AuthMode.MULTI_USER
    jwt_secret: SecretStr = SecretStr("change-me-in-production-please-32chars-min")
    jwt_access_ttl_min: int = 30
    jwt_refresh_ttl_days: int = 14
    app_token: SecretStr | None = None
    allow_open_registration: bool = False
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None
    # Refresh-token transport: HttpOnly cookie + CSRF double-submit (§24.2).
    # session_cookie_secure MUST be true behind HTTPS (enforced for prod below).
    session_cookie_name: str = "rag_refresh"
    csrf_cookie_name: str = "rag_csrf"
    csrf_header_name: str = "x-csrf-token"
    session_cookie_secure: bool = False
    session_cookie_samesite: str = "lax"  # lax | strict | none
    session_cookie_domain: str | None = None

    # ── LLM (generation) ─────────────────────────────────────────────────
    llm_provider: LLMProviderName = LLMProviderName.OPENAI
    llm_model: str = "gpt-4o-mini"
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1024
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 3
    llm_fallback_provider: LLMProviderName | None = None
    llm_fallback_model: str | None = None
    llm_fallback_api_key: SecretStr | None = None
    response_cache_enabled: bool = False
    llm_cache_ttl: int = 86400

    # ── Embeddings ───────────────────────────────────────────────────────
    embedding_provider: EmbeddingProviderName = EmbeddingProviderName.FASTEMBED
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_api_key: SecretStr | None = None
    embedding_base_url: str | None = None
    embedding_max_batch: int = 64

    # ── Reranker ─────────────────────────────────────────────────────────
    reranker: RerankerName = RerankerName.FASTEMBED_CROSS_ENCODER
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    reranker_api_key: SecretStr | None = None

    # ── Retrieval (nested: RETRIEVAL__*) ─────────────────────────────────
    retrieval: RetrievalSettings = RetrievalSettings()

    # ── Chunking (docs/ARCHITECTURE.md §11) ──────────────────────────────
    chunk_token_fraction: float = 0.8
    chunk_target_tokens: int = 512
    chunk_overlap_fraction: float = 0.15
    contextual_prefix_template: str = "{title}"

    # ── Ingestion (docs/ARCHITECTURE.md §8, §9, §30) ─────────────────────
    max_upload_mb: int = 25
    max_request_mb: int = 32
    min_file_bytes: int = 8
    max_pages: int = 1500
    max_chunks_per_doc: int = 5000
    min_text_chars_per_page: int = 30
    min_doc_chars: int = 20
    archive_max_uncompressed_mb: int = 200
    archive_max_entries: int = 2000
    archive_max_ratio: int = 120
    parse_timeout_s: int = 120
    parse_max_memory_mb: int = 1024
    ingest_max_attempts: int = 3
    worker_max_jobs: int = 4
    embedding_max_concurrency: int = 2
    qdrant_upsert_batch: int = 128
    reconcile_interval_s: int = 300
    reconcile_batch: int = 500
    indexing_stale_seconds: int = 900
    stale_grace_seconds: int = 60
    cutover_grace_seconds: int = 300
    trace_retention_days: int = 90
    embedding_supported_langs: str = "en"

    # ── Storage ──────────────────────────────────────────────────────────
    storage_backend: StorageBackend = StorageBackend.LOCAL
    storage_local_path: str = "/data/uploads"
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_region: str = "us-east-1"

    # ── PostgreSQL ───────────────────────────────────────────────────────
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "rag"
    postgres_password: SecretStr = SecretStr("rag_local_dev")
    postgres_db: str = "rag"
    postgres_connect_timeout_s: float = 5.0
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_echo: bool = False

    # ── Qdrant ───────────────────────────────────────────────────────────
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: SecretStr | None = SecretStr("qdrant_local_dev")
    qdrant_timeout_s: float = 15.0
    qdrant_search_ef: int = 128
    qdrant_vectors_on_disk: bool = False

    # ── Redis ────────────────────────────────────────────────────────────
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: SecretStr = SecretStr("redis_local_dev")
    redis_db: int = 0
    redis_timeout_s: float = 5.0

    # ── HTTP / ops ───────────────────────────────────────────────────────
    cors_allow_origins: str = "http://localhost:8080,http://127.0.0.1:8080,http://localhost:5173"
    readiness_timeout_s: float = 5.0
    bootstrap_wait_s: float = 60.0
    rate_limit_enabled: bool = True
    rate_limit_per_min: int = 120
    rate_limit_burst: int = 40
    metrics_enabled: bool = True
    trusted_proxies: str = "127.0.0.1,::1"
    worker_health_port: int = 8080
    status_poll_interval_s: float = 2.0
    kb_monthly_cost_soft_limit_usd: float = 0.0
    sentry_dsn: str | None = None
    otel_enabled: bool = False

    # ── Evaluation (docs/ARCHITECTURE.md §33) ────────────────────────────
    eval_judge_provider: LLMProviderName | None = None
    eval_judge_model: str | None = None
    eval_judge_api_key: SecretStr | None = None
    eval_bootstrap_n: int = 1000
    eval_dataset_root: str = ""  # empty → repo-root eval/datasets (dev) or packaged path
    seed_on_bootstrap: bool = False

    # ── validators ───────────────────────────────────────────────────────
    @field_validator("app_log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, value: object) -> str:
        text = str(value).upper()
        if text not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"APP_LOG_LEVEL must be a standard level, got {value!r}")
        return text

    @field_validator("session_cookie_samesite", mode="before")
    @classmethod
    def _normalise_samesite(cls, value: object) -> str:
        text = str(value).lower()
        if text not in {"lax", "strict", "none"}:
            raise ValueError("SESSION_COOKIE_SAMESITE must be lax, strict or none")
        return text

    # ── derived helpers ──────────────────────────────────────────────────
    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_allow_origins.split(",") if item.strip()]

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [item.strip() for item in self.trusted_proxies.split(",") if item.strip()]

    @property
    def supported_langs(self) -> tuple[str, ...]:
        return tuple(x.strip() for x in self.embedding_supported_langs.split(",") if x.strip())

    @property
    def postgres_dsn(self) -> str:
        pwd = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{pwd}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_dsn(self) -> str:
        pwd = self.redis_password.get_secret_value()
        return f"redis://:{pwd}@{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def bind_is_loopback(self) -> bool:
        host = self.bind_host.strip()
        if host in {"localhost", ""}:
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def safe_summary(self) -> dict[str, object]:
        return {
            "app_profile": self.app_profile.value,
            "app_version": self.app_version,
            "log_level": self.app_log_level,
            "auth_mode": self.auth_mode.value,
            "bind_host": self.bind_host,
            "llm_provider": self.llm_provider.value,
            "llm_model": self.llm_model,
            "llm_key_configured": _secret_present(self.llm_api_key),
            "llm_fallback_provider": (
                self.llm_fallback_provider.value if self.llm_fallback_provider else None
            ),
            "embedding_provider": self.embedding_provider.value,
            "embedding_model": self.embedding_model,
            "reranker": self.reranker.value,
            "fusion_strategy": self.retrieval.fusion_strategy.value,
            "storage_backend": self.storage_backend.value,
            "postgres": f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}",
            "qdrant_url": self.qdrant_url,
            "redis": f"{self.redis_host}:{self.redis_port}/{self.redis_db}",
        }

    def redacted_config(self) -> dict[str, object]:
        """Secret-free config allowlist for evaluation snapshots (docs/ARCHITECTURE.md §33.5)."""
        allow = {
            "app_version",
            "prompt_version",
            "llm_provider",
            "llm_model",
            "llm_temperature",
            "llm_max_tokens",
            "embedding_provider",
            "embedding_model",
            "reranker",
            "reranker_model",
            "chunk_token_fraction",
            "chunk_target_tokens",
            "chunk_overlap_fraction",
            "contextual_prefix_template",
        }
        out: dict[str, object] = {}
        for key in allow:
            value = getattr(self, key)
            out[key] = value.value if isinstance(value, StrEnum) else value
        out["retrieval"] = self.retrieval.model_dump(mode="json")
        return out


def _secret_present(value: SecretStr | None) -> bool:
    return value is not None and bool(value.get_secret_value().strip())


def _format_problems(problems: list[str]) -> str:
    body = "\n".join(f"  - {p}" for p in problems)
    return f"Invalid configuration ({len(problems)} problem(s)):\n{body}"


def validate_consistency(settings: Settings) -> None:
    """Cross-field and environment checks. Raises :class:`ConfigError` listing every
    problem at once (docs/ARCHITECTURE.md §26)."""

    problems: list[str] = []

    if settings.app_profile.is_runtime:
        if settings.llm_provider in FAKE_LLM_PROVIDERS:
            problems.append(
                f"LLM_PROVIDER={settings.llm_provider.value} is not permitted with "
                f"APP_PROFILE={settings.app_profile.value}. Fake providers are restricted "
                "to APP_PROFILE=ci or APP_PROFILE=test."
            )
        if settings.embedding_provider in FAKE_EMBEDDING_PROVIDERS:
            problems.append(
                f"EMBEDDING_PROVIDER={settings.embedding_provider.value} is not permitted "
                f"with APP_PROFILE={settings.app_profile.value}. Fake providers are "
                "restricted to APP_PROFILE=ci or APP_PROFILE=test."
            )

    if settings.llm_provider in HOSTED_LLM_PROVIDERS and not _secret_present(settings.llm_api_key):
        problems.append(
            f"LLM_PROVIDER={settings.llm_provider.value} requires LLM_API_KEY. "
            "Set LLM_API_KEY in your environment (.env), or run "
            "`docker compose --profile local up` for the fully local stack "
            "(LLM_PROVIDER=ollama)."
        )

    ollama_base_url = (settings.llm_base_url or "").strip()
    if settings.llm_provider is LLMProviderName.OLLAMA and not ollama_base_url:
        problems.append(
            "LLM_PROVIDER=ollama requires LLM_BASE_URL (for example http://ollama:11434)."
        )

    if (
        settings.llm_fallback_provider is not None
        and settings.llm_fallback_provider in HOSTED_LLM_PROVIDERS
        and not _secret_present(settings.llm_fallback_api_key)
    ):
        problems.append(
            f"LLM_FALLBACK_PROVIDER={settings.llm_fallback_provider.value} requires "
            "LLM_FALLBACK_API_KEY."
        )

    fallback_keys = sorted(k for k in os.environ if k.upper().startswith("EMBEDDING_FALLBACK"))
    if fallback_keys:
        problems.append(
            "Embedding-provider fallback is forbidden — it would mix incompatible vector "
            f"spaces (docs/ARCHITECTURE.md §16.3). Remove: {', '.join(fallback_keys)}."
        )

    if settings.auth_mode is AuthMode.SINGLE_USER and not settings.bind_is_loopback:
        problems.append(
            f"AUTH_MODE=single_user requires a loopback BIND_HOST; got {settings.bind_host!r}. "
            "Use AUTH_MODE=multi_user for a non-loopback bind (docs/ARCHITECTURE.md §25.2)."
        )

    if settings.auth_mode is AuthMode.MULTI_USER and settings.app_profile is AppProfile.PROD:
        secret = settings.jwt_secret.get_secret_value()
        if secret == "change-me-in-production-please-32chars-min" or len(secret) < 32:
            problems.append("JWT_SECRET must be set to a strong value (>= 32 chars) in prod.")
        if not settings.session_cookie_secure:
            problems.append(
                "SESSION_COOKIE_SECURE must be true in prod so the refresh-token cookie is "
                "only sent over HTTPS (docs/ARCHITECTURE.md §24.2)."
            )

    if settings.session_cookie_samesite == "none" and not settings.session_cookie_secure:
        problems.append(
            "SESSION_COOKIE_SAMESITE=none requires SESSION_COOKIE_SECURE=true (browser rule)."
        )

    if settings.storage_backend is StorageBackend.S3 and not settings.s3_bucket:
        problems.append("STORAGE_BACKEND=s3 requires S3_BUCKET (and S3 credentials).")

    if problems:
        raise ConfigError(_format_problems(problems))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        settings = Settings()
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(f"Invalid configuration:\n{exc}") from exc
    validate_consistency(settings)
    return settings
