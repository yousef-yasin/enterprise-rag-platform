"""`rag` CLI behaviour (docs/ARCHITECTURE.md §27.2, Phase 0 gate)."""

from __future__ import annotations

import pytest

from app import __version__
from app.cli.main import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_config_check_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config-check"]) == 0
    assert "configuration OK" in capsys.readouterr().out


def test_config_check_reports_missing_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APP_PROFILE", "local")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    exit_code = main(["config-check"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "LLM_API_KEY" in err
    assert "docker compose --profile local up" in err


def test_bootstrap_skip_migrate_only_validates(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["bootstrap", "--skip-migrate"]) == 0
    assert "configuration OK" in capsys.readouterr().out


def test_no_subcommand_is_an_error() -> None:
    with pytest.raises(SystemExit):
        main([])
