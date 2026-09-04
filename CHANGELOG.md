# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Phase 8 — Frontend.** Vite + React 18 + TypeScript (strict) SPA: login /
  registration, knowledge-base and member management, document upload with live
  ingestion status (SSE + polling backstop), streaming chat with a citation
  panel and `[[n]]` chips, feedback thumbs, an evaluation runs view, and API-key
  management. Generated API client workflow (`npm run gen:api`) with a
  hand-written fallback. Strict CSP + allowlist markdown sanitizer (no
  `dangerouslySetInnerHTML`); image markdown is inert. Multi-stage
  Docker build (node → nginx). Playwright golden E2E (`tests/e2e/golden.spec.ts`).
- **Phase 9 — Evaluation.** `EvaluationService` running the real pipeline over
  JSONL datasets; retrieval (recall/precision/MRR/nDCG/hit @ k), answer
  (`token_f1` + LLM judge correctness/faithfulness/relevance), citation
  (precision/recall + hard "cited ⊆ context"), abstention (precision/recall/F1),
  and latency/token/cost metrics; bootstrap 95% CIs. `rag eval run|compare|
  calibrate-reranker`, `rag traces export`, `/eval/*` endpoints, committed
  `eval/corpus/handbook` + `smoke`/`dev` datasets, `eval-nightly` workflow.
- **Phase 10 — Hardening & ops.** Sliding-window rate limiting (429 +
  `Retry-After`, `TRUSTED_PROXIES`-aware, fails open). Prometheus `/metrics`
  (HTTP, per-stage ingestion/retrieval latency, `rag_degraded_total`,
  `rag_abstention_total`, `rag_llm_tokens_total`, `rag_llm_cost_usd_total`,
  citation counters). CI: `integration`, `frontend`, `e2e-smoke`, and `security`
  (pip-audit, bandit, npm audit, gitleaks, trivy) jobs. `provider-live` (manual/
  nightly) and `release` (GHCR image publish) workflows. `LICENSE` (Apache-2.0),
  `SECURITY.md`, `CONTRIBUTING.md`, `.env.example`, `docs/OPERATIONS.md`,
  `docs/RESULTS.md`, README with Path A / Path B quick-starts and badges.

### Security

- Bumped `react-router-dom` 6.26.2 → 6.30.6 and `markdown-it` 14.1.0 → 14.3.1 to
  clear all `npm audit` **high**-severity advisories. Two **moderate** advisories
  remain in `react-router` (open redirect via user-controlled navigation targets;
  SSR-hydration constructor injection) — neither is reachable here: every route
  target is a hard-coded literal and the app is a client-only SPA with no SSR.
  Closing them needs the breaking `react-router` v7 upgrade (tracked separately).
- Frontend image now runs **non-root**: `nginxinc/nginx-unprivileged` (uid 101),
  listening on container port 8080 (trivy DS-0002). The published host port is
  unchanged (`WEB_PORT`, default `127.0.0.1:8080`).
- `compute_embedding_profile_id` marks its SHA-1 as `usedforsecurity=False` (it is
  a config identity key, not a security hash) — clears bandit B324.
- `app/server.py` annotates the intentional `host="0.0.0.0"` container bind with
  `# nosec B104` (the port is published on loopback only by compose).
- Dev tooling: `@playwright/test` 1.47.2 → 1.58.0; Playwright's local dev-server
  base URL uses `localhost` (Vite v5 binds IPv6 `::1` by default).

### Fixed

- **Documents page no longer gets stuck on a `processing` document.** The frontend
  `DocumentStatus` type and its "active" set listed non-existent per-phase statuses
  (`parsing`/`chunking`/`indexing`); the backend uses a single `processing` status
  with a `failed_stage` field. A document in `processing` was treated as terminal,
  so status polling stopped and the badge never advanced to `ready`. Types and the
  polling set now match `backend/app/core/enums.py::DocumentStatus`.

### Changed

- **Refresh-token transport moved to an `HttpOnly` cookie with CSRF protection**
  (§24.2). `POST /auth/login` and `/auth/refresh` no longer return
  `refresh_token` in the body — it is set as an `HttpOnly`, `SameSite=Lax` cookie
  scoped to `/api/v1/auth`. `/auth/refresh` and `/auth/logout` require an
  `X-CSRF-Token` header matching the `rag_csrf` companion cookie (double-submit).
  New settings: `SESSION_COOKIE_SECURE` (forced true for `APP_PROFILE=prod`),
  `SESSION_COOKIE_SAMESITE`, `SESSION_COOKIE_DOMAIN`. The frontend keeps the
  access token in memory only and restores sessions via the cookie on load.
- `docker-compose.yml`: `api`/`worker` now mount the `uploads` and `modelcache`
  volumes and receive the full auth/JWT/storage environment; `bootstrap` runs
  migrations + admin creation before `api`/`worker` start.

## [0.0.0] — scaffolding

- Phase 0–7: repository scaffolding, config with fail-fast validation, CI
  skeleton, Docker skeleton, auth/RBAC/knowledge bases, persistence + async
  Alembic migrations, upload + secure parsing + ingestion, PG↔Qdrant consistency
  + reconciliation, embeddings, hybrid retrieval + fusion + reranking, query
  contextualization, RAG chat with streaming, citations, abstention, token
  budgets, cost tracking, and conversations.
