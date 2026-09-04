"""Shared test fixtures.

`app.main` and `app.workers.worker` evaluate configuration at import time (module
factory / arq settings). The ``os.environ.setdefault`` calls below run before test
collection so those imports succeed; they never override a value a test set
deliberately. The autouse ``base_env`` fixture then gives each test a clean,
isolated environment and resets the ``get_settings`` cache.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("APP_PROFILE", "test")
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("EMBEDDING_PROVIDER", "fake")
os.environ.setdefault("APP_LOG_JSON", "false")

from app.config import get_settings

# Provider / profile vars must be deterministic for unit tests, so they are wiped
# and re-set below. Infrastructure connection vars (POSTGRES_*, QDRANT_*, REDIS_*)
# are deliberately left alone so `make test-integration` can point them at
# 127.0.0.1; unit tests that need specific values pass them to ``Settings`` directly.
_MANAGED_PREFIXES = (
    "APP_",
    "LLM_",
    "EMBEDDING_",
    "RERANKER",
)


@pytest.fixture(autouse=True)
def base_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in list(os.environ):
        if key.upper().startswith(_MANAGED_PREFIXES):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("APP_PROFILE", "test")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("APP_LOG_JSON", "false")

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
