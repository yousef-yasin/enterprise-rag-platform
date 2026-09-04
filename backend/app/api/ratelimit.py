"""Sliding-window rate limiting (docs/ARCHITECTURE.md §22, §28.4).

Pure ASGI middleware. Two Redis sorted-set windows per client:

  * a 60 s window capped at ``RATE_LIMIT_PER_MIN``
  * a 1 s window capped at ``RATE_LIMIT_BURST`` (smooths spikes)

The client key is the authenticated principal where a bearer token / API key is
present (so one noisy key cannot exhaust a shared NAT'd IP), otherwise the
caller IP resolved through ``TRUSTED_PROXIES``. Fails open: if Redis is
unreachable the request is allowed and a warning is logged.
"""

from __future__ import annotations

import hashlib
import ipaddress
import secrets
import time

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings
from app.core.security import API_KEY_PREFIX
from app.infra.redis.client import get_redis
from app.infra.redis.namespaces import RATELIMIT

_log = structlog.get_logger("app.ratelimit")

_EXEMPT_PREFIXES = ("/health", "/api/v1/health", "/metrics", "/api/v1/docs", "/api/v1/openapi.json")


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self._app = app
        self._settings = settings
        self._per_min = settings.rate_limit_per_min
        self._burst = settings.rate_limit_burst
        self._trusted = _parse_networks(settings.trusted_proxy_list)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._settings.rate_limit_enabled:
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET")
        if method == "OPTIONS" or path.startswith(_EXEMPT_PREFIXES):
            await self._app(scope, receive, send)
            return

        client_key = self._client_key(scope)
        allowed, retry_after = await self._check(client_key)
        if allowed:
            await self._app(scope, receive, send)
            return

        await _send_429(send, retry_after)

    # ── window check ───────────────────────────────────────────────────────
    async def _check(self, client_key: str) -> tuple[bool, int]:
        try:
            redis = get_redis(self._settings)
            now = time.time()
            windows = (
                (f"{RATELIMIT}m:{client_key}", 60.0, self._per_min),
                (f"{RATELIMIT}s:{client_key}", 1.0, self._burst),
            )
            for key, span, limit in windows:
                pipe = redis.pipeline()
                pipe.zremrangebyscore(key, 0, now - span)
                pipe.zcard(key)
                pipe.zadd(key, {f"{now}:{secrets.token_hex(8)}": now})
                pipe.expire(key, int(span) + 1)
                _removed, count, _added, _exp = await pipe.execute()
                if int(count) >= limit:
                    # roll back our own token so it does not count against the caller
                    await redis.zpopmax(key)
                    return False, int(span)
            return True, 0
        except Exception as exc:
            _log.warning("ratelimit.unavailable", error=str(exc))
            return True, 0

    # ── client identity ────────────────────────────────────────────────────
    def _client_key(self, scope: Scope) -> str:
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            digest = hashlib.sha256(token.encode()).hexdigest()[:16]
            kind = "key" if token.startswith(API_KEY_PREFIX) else "jwt"
            return f"{kind}:{digest}"
        return f"ip:{self._client_ip(scope, headers)}"

    def _client_ip(self, scope: Scope, headers: dict[str, str]) -> str:
        peer = ""
        client = scope.get("client")
        if client:
            peer = client[0]
        forwarded = headers.get("x-forwarded-for", "")
        if forwarded and _is_trusted(peer, self._trusted):
            # take the right-most untrusted address in the chain
            chain = [p.strip() for p in forwarded.split(",") if p.strip()]
            for candidate in reversed(chain):
                if not _is_trusted(candidate, self._trusted):
                    return candidate
            if chain:
                return chain[0]
        return peer or "unknown"


def _parse_networks(values: list[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for raw in values:
        try:
            nets.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            continue
    return nets


def _is_trusted(addr: str, nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network]) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in nets)


async def _send_429(send: Send, retry_after: int) -> None:
    body = (
        b'{"error":{"code":"rate_limited","message":"too many requests; slow down",'
        b'"details":null,"request_id":null}}'
    )
    await send(
        {
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"retry-after", str(max(1, retry_after)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
