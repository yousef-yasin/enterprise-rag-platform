"""FastAPI application factory (docs/ARCHITECTURE.md §3, §23).

``create_app`` calls :func:`~app.config.get_settings` eagerly, so an invalid
configuration fails at import time. The container entrypoint (``app.server``)
catches that and prints a clean message before uvicorn starts.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.health import health_router
from app.api.metrics import MetricsMiddleware, metrics_router
from app.api.middleware import RequestIDMiddleware
from app.api.ratelimit import RateLimitMiddleware
from app.api.v1 import api_router
from app.config import get_settings
from app.core.logging import configure_logging

_log = structlog.get_logger("app.main")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(level=settings.app_log_level, json_output=settings.app_log_json)
    _log.info("api.startup", **settings.safe_summary())
    try:
        yield
    finally:
        from app.infra.db.session import dispose_engine

        await dispose_engine()
        _log.info("api.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()  # fail-fast on invalid configuration
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/v1/docs",
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    # add_middleware prepends: last added is outermost. Desired outer->inner:
    # RequestID -> CORS -> Metrics -> RateLimit -> routers. (CORS above the rate
    # limiter so a browser can still read a 429; metrics count rate-limited calls.)
    app.add_middleware(RateLimitMiddleware, settings=settings)
    if settings.metrics_enabled:
        app.add_middleware(MetricsMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    if settings.metrics_enabled:
        app.include_router(metrics_router)
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
