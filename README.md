# Enterprise RAG Platform

[![ci](https://github.com/yousef-yasin/enterprise-rag-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/yousef-yasin/enterprise-rag-platform/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.12-blue.svg)](backend/pyproject.toml)
[![node](https://img.shields.io/badge/node-%3E%3D20-blue.svg)](frontend/package.json)

A production-oriented, self-hostable Retrieval-Augmented Generation platform:
multi-user knowledge bases, secure document ingestion, hybrid (dense + sparse)
retrieval with reranking, streaming grounded chat with citations and abstention,
an offline evaluation harness with confidence intervals, and first-class
operability. No vendor lock-in — swap the LLM, embedding, and reranker providers
by configuration.

**Status:** all planned phases are implemented and tested — ingestion, hybrid
retrieval + reranking, streaming RAG chat with citations/abstention, multi-user
auth with cookie-based sessions + CSRF, a React frontend, an evaluation harness,
and CI/security hardening (lint, strict mypy, unit + integration tests, a
Playwright E2E, and dependency/secret/container scans). What's genuinely still
open: real-provider evaluation numbers haven't been recorded yet (the harness
runs on every push with deterministic fake providers; see
[Evaluation](#evaluation)), and a couple of moderate, non-exploitable frontend
dependency advisories are tracked in [`CHANGELOG.md`](CHANGELOG.md).

The full design rationale is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
(Revision 2) and the ADRs in [`docs/adr/`](docs/adr).

---

## What it does

| Area | Highlights |
|---|---|
| **Ingestion** | PDF / DOCX / TXT / MD, magic-byte + zip-bomb + XXE guards, structure-aware chunking, contextual heading prefixes, a documented PG↔Qdrant write protocol with a reconciler |
| **Retrieval** | Qdrant named dense + sparse (BM25-style) vectors, RRF / weighted / DBSF fusion, cross-encoder reranking with timeout→degrade, near-duplicate suppression |
| **Generation** | OpenAI / Anthropic / Ollama adapters behind one interface, SSE streaming, token-budget-aware context assembly, `[[n]]` citations with a groundedness heuristic, calibrated abstention |
| **Multi-user** | Users, knowledge bases + membership roles (owner/editor/viewer), API keys with scopes intersected against membership, append-only audit log, cookie-based sessions |
| **Evaluation** | JSONL datasets, retrieval / answer / faithfulness / citation / abstention / cost metrics, bootstrap 95% CIs, `compare`, `calibrate-reranker`, an LLM judge with family-separation warnings |
| **Ops** | `/health/live` + `/health/ready` (per-dependency), Prometheus `/metrics`, sliding-window rate limiting, structured logs with request IDs, retrieval traces + export |
| **Frontend** | React 18 + TS (strict), streaming chat UI, citation panel, document upload with live status, KB/member management, strict CSP + markdown sanitizer (no `dangerouslySetInnerHTML`) |

---

## Try it in 60 seconds (no API key)

Needs Docker, `bash`, `curl`, and `jq` (a POSIX shell — on Windows, run this
from WSL2 or Git Bash).

```bash
git clone https://github.com/yousef-yasin/enterprise-rag-platform
cd enterprise-rag-platform
make e2e
```

This brings up the full Docker stack with deterministic **fake providers** (no
external calls, no API key needed) and runs a scripted golden flow: register →
create a knowledge base → upload a fixture document → wait for it to be
indexed → ask a question → assert a grounded, cited answer comes back — then
tears everything down. Read [`scripts/e2e_smoke.sh`](scripts/e2e_smoke.sh) to
see exactly what it checks. To leave the stack up and click around the UI
yourself instead, run the same two commands manually — see the `e2e` target in
the [`Makefile`](Makefile) — then open <http://127.0.0.1:8080>.

---

## Quick start

Two paths for running it with a real model. Both come up with **no `.env`
file** — every setting has a safe local default.

### Path A — hosted LLM (recommended)

You need one API key (OpenAI by default).

```bash
export LLM_API_KEY=sk-...              # OpenAI; or set LLM_PROVIDER=anthropic + an Anthropic key
export BOOTSTRAP_ADMIN_EMAIL=you@example.com
export BOOTSTRAP_ADMIN_PASSWORD=change-me-please

docker compose up --build
```

- UI: <http://127.0.0.1:8080>
- API docs: <http://127.0.0.1:8000/api/v1/docs>

Embeddings and reranking run locally on-CPU via ONNX (`fastembed`) — no GPU, no
`torch`. The first start downloads the small models (~150 MB) into a cached volume.

### Path B — fully local (Ollama)

No external API calls at all.

```bash
export LLM_PROVIDER=ollama
export LLM_MODEL=llama3.1
export LLM_BASE_URL=http://ollama:11434
export BOOTSTRAP_ADMIN_EMAIL=you@example.com
export BOOTSTRAP_ADMIN_PASSWORD=change-me-please

docker compose --profile local up --build
docker compose exec ollama ollama pull llama3.1
```

Either path: set `SEED_ON_BOOTSTRAP=true` to pre-load a small demo knowledge
base so there's something to ask about right away. See
[`.env.example`](.env.example) for every knob and
[`docs/OPERATIONS.md`](docs/OPERATIONS.md) for running it for real.

---

## Demo

Screenshots and a short walkthrough GIF haven't been captured yet — see
[`docs/screenshots/`](docs/screenshots/) for the planned shot list. In the
meantime, `make e2e` above is a scripted, zero-setup proof that the full flow
(upload → ingest → cited answer) works end to end, and the API is self-
documenting at `/api/v1/docs` once the stack is up.

---

## Develop

```bash
# backend
cd backend
uv sync
make -C .. dev            # compose up with hot-reload for api + worker + Vite

# or run pieces directly
uv run uvicorn app.main:app --reload
uv run arq app.workers.worker.WorkerSettings

# frontend
cd frontend && npm install && npm run dev     # proxies the API on :8000
```

### Checks (what CI runs)

```bash
make check                # ruff + ruff format + mypy (strict) + unit tests
make test-integration     # spins compose.test.yml, runs tests/integration
make frontend-check       # frontend lint + typecheck + vitest + build
make eval                 # smoke evaluation split with fake providers
make e2e                  # full stack + the golden E2E flow (see above)
```

Run `make help` for the full target list.

---

## Evaluation

```bash
# ingest eval/corpus/handbook/* into a KB, then:
cd backend
uv run rag eval run handbook --kb <kb-uuid> --split dev --label "rrf+rerank"
uv run rag eval compare <run-a> <run-b>          # bootstrap difference CIs
uv run rag eval calibrate-reranker --kb <kb-uuid> --dataset handbook --split dev
uv run rag traces export --since 2026-01-01 --out traces.jsonl
```

`eval/datasets/handbook/` ships `smoke` (CI) and `dev` splits today; a held-out
`test` split is added alongside the first real-provider run (see below) so it
can't leak into iteration. The harness, metrics (retrieval, answer correctness/
faithfulness, citation precision/recall, abstention, cost/latency — all with
bootstrap 95% CIs), and reproduction commands are final and run in CI on every
push (`smoke` split, fake providers — verifies the harness, not answer
quality). **Real-provider numbers have not been recorded yet**;
[`docs/RESULTS.md`](docs/RESULTS.md) documents the methodology and is left as
explicit placeholders (`_tbd_`) rather than invented figures until that run
happens.

---

## Security

- **Untrusted by default**: uploaded documents, retrieved chunk text, and model
  output are all treated as untrusted. The parser enforces type/size/zip-bomb/
  XXE limits; prompts are spotlighted with fenced, clearly-marked context;
  the frontend renders answers through an allowlist markdown sanitizer with a
  strict CSP and never uses `dangerouslySetInnerHTML`.
- **Isolation** is the knowledge-base + membership boundary — a non-member gets
  `404`, not `403`, and retrieval sets the KB filter server-side.
- **Sessions**: the access token lives in memory only; the refresh token is an
  `HttpOnly`, `SameSite=Lax` cookie with a CSRF double-submit token on
  `/auth/refresh` and `/auth/logout`. See [`SECURITY.md`](SECURITY.md#security-model--quick-reference)
  for the full model, including its stated limitations (no refresh-token
  denylist in v1).
- **CI security gate**: `bandit`, `pip-audit`, `npm audit`, `gitleaks`, and
  `trivy` run on every push; findings and fixes are tracked in
  [`CHANGELOG.md`](CHANGELOG.md).
- Found a vulnerability? See [`SECURITY.md`](SECURITY.md) — please don't open a
  public issue.

---

## Repository layout

```
backend/     FastAPI app, worker, providers, core pipeline, Alembic, tests
frontend/    Vite + React + TS SPA, Playwright golden E2E
eval/        corpus/  +  datasets/<name>/{smoke,dev,test}.jsonl
seed/        small demo corpus loaded when SEED_ON_BOOTSTRAP=true
docs/        ARCHITECTURE.md (source of truth), adr/, OPERATIONS.md, RESULTS.md
scripts/     e2e_smoke.sh, run_eval.py
```

---

## Contributing & security

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, the check gate, PR expectations
- [`SECURITY.md`](SECURITY.md) — supported versions and how to report a vulnerability
- [`CHANGELOG.md`](CHANGELOG.md) — Keep a Changelog + SemVer
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) — Contributor Covenant v2.1

Licensed under [Apache-2.0](LICENSE).
