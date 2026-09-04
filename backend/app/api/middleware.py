"""Request-ID middleware (docs/ARCHITECTURE.md §28.1).

Pure ASGI (no ``BaseHTTPMiddleware``). Reads an inbound ``X-Request-ID`` or mints
one, binds it to the structlog context and the request context var, and echoes it
on the response.
"""

from __future__ import annotations

import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.context import request_id_var

REQUEST_ID_HEADER = "x-request-id"


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = _inbound_request_id(scope) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self._app(scope, receive, send_with_header)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
            request_id_var.reset(token)


def _inbound_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == REQUEST_ID_HEADER.encode():
            text = value.decode("latin-1").strip()
            return text or None
    return None
