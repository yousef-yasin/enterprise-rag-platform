"""API container entrypoint fail-fast behaviour (docs/ARCHITECTURE.md §2, Phase 0 gate)."""

from __future__ import annotations

import pytest

from app import server


def test_entrypoint_fails_fast_on_missing_hosted_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import uvicorn

    def _must_not_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("uvicorn.run must not be reached on a config failure")

    monkeypatch.setattr(uvicorn, "run", _must_not_run)
    monkeypatch.setenv("APP_PROFILE", "local")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    exit_code = server.main()

    assert exit_code == 1
    assert "LLM_API_KEY" in capsys.readouterr().err


def test_entrypoint_starts_uvicorn_when_config_is_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uvicorn

    started: dict[str, object] = {}

    def _fake_run(app_path: str, **kwargs: object) -> None:
        started["app_path"] = app_path

    monkeypatch.setattr(uvicorn, "run", _fake_run)

    exit_code = server.main()

    assert exit_code == 0
    assert started["app_path"] == "app.main:app"


def test_entrypoint_defaults_to_port_8000_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    started: dict[str, object] = {}
    monkeypatch.setattr(uvicorn, "run", lambda _path, **kwargs: started.update(kwargs))
    monkeypatch.delenv("PORT", raising=False)

    assert server.main() == 0
    assert started["port"] == 8000


def test_entrypoint_binds_platform_assigned_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cloud Run (and similar PaaS targets) assign the listen port via $PORT."""
    import uvicorn

    started: dict[str, object] = {}
    monkeypatch.setattr(uvicorn, "run", lambda _path, **kwargs: started.update(kwargs))
    monkeypatch.setenv("PORT", "8080")

    assert server.main() == 0
    assert started["port"] == 8080


def test_entrypoint_rejects_non_integer_port(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import uvicorn

    def _must_not_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("uvicorn.run must not be reached on an invalid PORT")

    monkeypatch.setattr(uvicorn, "run", _must_not_run)
    monkeypatch.setenv("PORT", "not-a-number")

    exit_code = server.main()

    assert exit_code == 1
    assert "PORT" in capsys.readouterr().err
