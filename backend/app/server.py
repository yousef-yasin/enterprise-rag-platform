"""API container entrypoint (docs/ARCHITECTURE.md §2 — fail-fast).

Validates configuration first and prints a clean, actionable message on failure
(no traceback), then hands off to uvicorn. Set ``APP_RELOAD=true`` for the dev
hot-reload workflow.
"""

from __future__ import annotations

import os
import sys

from app.config import ConfigError, get_settings

_RELOAD_VALUES = {"1", "true", "yes", "on"}


def _reload_enabled() -> bool:
    return os.environ.get("APP_RELOAD", "").strip().lower() in _RELOAD_VALUES


def main() -> int:
    try:
        get_settings()
    except ConfigError as exc:
        print(f"\n{exc}\n", file=sys.stderr, flush=True)
        return 1

    import uvicorn

    reload_enabled = _reload_enabled()
    uvicorn.run(
        "app.main:app",
        # Binds all interfaces inside the container; compose publishes the port on
        # 127.0.0.1 only, and a non-loopback bind also forces AUTH_MODE=multi_user.
        host="0.0.0.0",  # nosec B104
        port=8000,
        reload=reload_enabled,
        reload_dirs=["/app/app"] if reload_enabled else None,
        log_config=None,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
