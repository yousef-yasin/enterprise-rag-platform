"""`/metrics` endpoint + HTTP metrics middleware (docs/ARCHITECTURE.md §28.4)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.obs.metrics import HTTP_DURATION, HTTP_REQUESTS, render_latest

metrics_router = APIRouter(tags=["observability"])


@metrics_router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    payload, content_type = render_latest()
    return Response(content=payload, media_type=content_type)


class MetricsMiddleware:
    """Records request count + latency, keyed by the matched route template so the
    label cardinality stays bounded (``/documents/{document_id}`` not the id)."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "") == "/metrics":
            await self._app(scope, receive, send)
            return

        method: str = scope.get("method", "GET")
        start = time.perf_counter()
        status_holder = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = int(message["status"])
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
        finally:
            template = _route_template(scope)
            elapsed = time.perf_counter() - start
            status_class = f"{status_holder['code'] // 100}xx"
            HTTP_REQUESTS.labels(method=method, path=template, status=status_class).inc()
            HTTP_DURATION.labels(method=method, path=template).observe(elapsed)


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path_format = getattr(route, "path_format", None) or getattr(route, "path", None)
    if isinstance(path_format, str):
        return path_format
    return str(scope.get("path", "unknown"))
