# Operations

Running enterprise-rag-platform for real. Companion to
[`ARCHITECTURE.md`](ARCHITECTURE.md) §27–28.

## Services

| Service | Purpose | Health | Scale |
|---|---|---|---|
| `postgres` | source of truth for chunk text, metadata, users, traces | `pg_isready` | 1 (use managed PG in prod) |
| `qdrant` | dense + sparse vectors, per-KB collections | `GET /readyz` | 1 (or a cluster) |
| `redis` | arq queue, job streams, rate-limit windows, caches — **AOF + `noeviction`** | `redis-cli ping` | 1 |
| `bootstrap` | one-shot: `alembic upgrade head` → admin creation → optional seed | exits 0 | — |
| `api` | FastAPI, stateless | `GET /health/live`, `GET /health/ready` | N behind a load balancer |
| `worker` | arq: ingestion, reindex cutover, cron (reconcile, trace GC, stream reaper) | `arq --check` | N (jobs are idempotent + advisory-locked) |
| `frontend` | nginx: static SPA + API reverse proxy + CSP | `GET /healthz` | N |

Start order is enforced by compose: infra healthy → `bootstrap` completes → `api`
+ `worker` → `api` healthy → `frontend`.

## First boot

```bash
export LLM_API_KEY=...                       # or the Ollama vars (Path B)
export BOOTSTRAP_ADMIN_EMAIL=admin@you.tld
export BOOTSTRAP_ADMIN_PASSWORD='...'        # omit → generated + printed once by bootstrap
export JWT_SECRET="$(openssl rand -hex 32)"  # REQUIRED in prod; startup refuses the default
export SESSION_COOKIE_SECURE=true            # REQUIRED in prod (HTTPS refresh-token cookie)
docker compose up -d --build
docker compose logs bootstrap                # confirm "bootstrap complete"
```

`APP_PROFILE=prod` additionally forbids the default `JWT_SECRET`,
`SESSION_COOKIE_SECURE=false`, fake providers, and a hosted LLM without a key —
all reported at once, before the server binds. Terminate TLS in front of the
`api` service (or set `SESSION_COOKIE_SECURE` only once HTTPS is in place, or the
refresh cookie will be dropped by browsers).

## Health & readiness

- `GET /health/live` — process is up (used by the container healthcheck).
- `GET /health/ready` — checks Postgres, Qdrant, Redis, the queue, and the
  embedding provider; returns **503 with the failing dependency named** when any
  is down. Point your load balancer here.

## Metrics

`GET /metrics` (Prometheus text). Key series (all `rag_` prefixed):

| Metric | Type | Use |
|---|---|---|
| `rag_http_request_duration_seconds` | histogram | API latency SLOs (labelled by route template) |
| `rag_ingestion_stage_seconds{stage}` | histogram | parse / embed / index / total durations |
| `rag_retrieval_stage_seconds{stage}` | histogram | embed / dense / sparse / fuse / rerank |
| `rag_degraded_total{component}` | counter | sparse or rerank fell back — alert on rate |
| `rag_abstention_total{reason}` | counter | refusal rate by cause (`empty_kb`, `no_results`, `low_confidence`) |
| `rag_llm_tokens_total{kind}` / `rag_llm_cost_usd_total` | counter | spend tracking |
| `rag_invalid_citation_total` / `rag_weak_citation_total` | counter | answer-grounding quality |
| `rag_ingestion_failures_total{reason}` | counter | parser / pipeline failures by taxonomy |

Suggested alerts: `/health/ready` failing; `rate(rag_degraded_total[15m]) > 0`
sustained; abstention rate spike; ingestion failure rate; p99 chat latency.

## Routine operations

```bash
# reconcile PG <-> Qdrant invariants on demand (also runs on a cron)
docker compose exec worker rag reconcile

# create users / API keys
docker compose exec api rag user create --email dev@you.tld --admin
docker compose exec api rag api-key create --email dev@you.tld --name ci --scope kb:read --scope chat

# export retrieval traces for offline analysis
docker compose exec api rag traces export --since 2026-01-01 --out /tmp/traces.jsonl
```

## Backups

- **Postgres** — regular `pg_dump` / managed snapshots. This is the authoritative
  store; Qdrant can be rebuilt from it via reindex.
- **Qdrant** — snapshot the `qdrantdata` volume, or accept a rebuild (reindex is
  O(corpus) in embedding cost).
- **Redis** — the AOF on `redisdata` covers the queue and in-flight job streams.
  Losing it drops queued jobs; the reconciler re-enqueues stuck documents.
- **`uploads` volume** — original files; needed for reprocessing.

## Upgrades

1. Read `CHANGELOG.md`.
2. Pull the new images / tag.
3. `bootstrap` runs `alembic upgrade head` before `api`/`worker` restart; a failed
   migration blocks them (no half-migrated serving).
4. An embedding-model or chunk-policy change requires a full **reindex** per KB —
   retrieval returns `409` until the KB's stored profile matches the running one.

## Common failures

| Symptom | Cause | Action |
|---|---|---|
| `api` won't start, config error listed | invalid/insecure config (e.g. default `JWT_SECRET` in prod) | fix the reported items — all are listed at once |
| retrieval returns `409 reindex` | KB indexed with a different embedding profile | reindex the KB, or restore the previous embedding config |
| documents stuck `processing` | worker down / crashed mid-job | bring the worker up; the reconciler re-enqueues after `INDEXING_STALE_SECONDS` |
| chat always abstains | empty KB, or reranker uncalibrated + weak retrieval | ingest content; run `rag eval calibrate-reranker` |
| `429` responses | rate limit | raise `RATE_LIMIT_PER_MIN`, or set `TRUSTED_PROXIES` so per-user keying works behind your LB |
