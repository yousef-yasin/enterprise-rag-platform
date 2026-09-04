"""Per-request context (docs/ARCHITECTURE.md §28.1).

The request id is bound here by :class:`~app.api.middleware.RequestIDMiddleware` and
read by the logging pipeline and the error handlers.
"""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    return request_id_var.get()
