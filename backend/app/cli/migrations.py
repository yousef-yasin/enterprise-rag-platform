"""Programmatic Alembic access for ``rag bootstrap`` (docs/ARCHITECTURE.md §27.2)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _config() -> Config:
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    return cfg


def upgrade_to_head() -> None:
    """Run ``alembic upgrade head`` using the async env (docs/ARCHITECTURE.md §27.2)."""

    command.upgrade(_config(), "head")
