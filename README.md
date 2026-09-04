# Enterprise RAG Platform

[![ci](https://github.com/yousef-yasin/enterprise-rag-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/yousef-yasin/enterprise-rag-platform/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.12-blue.svg)](backend/pyproject.toml)

A production-oriented, self-hostable Retrieval-Augmented Generation platform:
multi-user knowledge bases, secure document ingestion, hybrid (dense + sparse)
retrieval with reranking, streaming grounded chat with citations and abstention,
an offline evaluation harness with confidence intervals, and first-class
operability. No vendor lock-in — swap the LLM, embedding, and reranker providers
by configuration.

The full design rationale is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
(Revision 2) and the ADRs in [`docs/adr/`](docs/adr).

---

## What it does

| Area | Highlights |
|---|---|
| **Ingestion** | PDF / DOCX / TXT / MD, magic-byte + zip-bomb + XXE guards, structure-aware chunking, contextual heading prefixes, a documented PG↔Qdrant write protocol with a reconciler |
| **Retrieval** | Qdrant named dense + sparse (BM25-style) vectors, RRF / weighted / DBSF fusion, cross-encoder reranking with timeout→degrade, near-duplicate suppression |
| **Generation** | OpenAI / Anthropic / Ollama adapters behind one interface, SSE streaming, token-budget-aware context assembly, `[[n]]` citations with a groundedness heuristic, calibrated abstention |
| **Multi-user** | Users, knowledge bases + membership roles (owner/editor/viewer), API keys with scopes intersected against membership, append-only audit log, JWT sessions |
| **Evaluation** | JSONL datasets, retrieval / answer / faithfulness / citation / abstention / cost metrics, bootstrap 95% CIs, `compare`, `calibrate-reranker`, an LLM judge with family-separation warnings |
| **Ops** | `/health/live` + `/health/ready` (per-dependency), Prometheus `/metrics`, sliding-window rate limiting, structured logs with request IDs, retrieval traces + export |
| **Frontend** | React 18 + TS (strict), streaming chat UI, citation panel, document upload with live status, KB/member management, strict CSP + markdown sanitizer (no `dangerouslySetInnerHTML`) |

---

## Quick start

Two paths. Both come up with **no `.env` file** — every setting has a safe local
default.

### Path A — hosted LLM (recommended)

You need one API key (OpenAI by default).

```bash
git clone https://github.com/yousef-yasin/enterprise-rag-platform
cd enterprise-rag-platform

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

See [`.env.example`](.env.example) for every knob and
[`docs/OPERATIONS.md`](docs/OPERATIONS.md) for running it for real.

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
cd frontend && npm run lint && npm run typecheck && npm run test && npm run build
make eval                 # smoke evaluation split with fake providers
```

---

## Evaluation

```bash
# ingest eval/corpus/handbook/* into a KB, then:
cd backend
uv run rag eval run handbook --kb <kb-uuid> --split test --label "rrf+rerank"
uv run rag eval compare <run-a> <run-b>          # bootstrap difference CIs
uv run rag eval calibrate-reranker --kb <kb-uuid> --dataset handbook --split dev
uv run rag traces export --since 2026-01-01 --out traces.jsonl
```

Measured results on the committed corpus + `test` split live in
[`docs/RESULTS.md`](docs/RESULTS.md).

---

## Repository layout

```
backend/     FastAPI app, worker, providers, core pipeline, Alembic, tests
frontend/    Vite + React + TS SPA, Playwright golden E2E
eval/        corpus/  +  datasets/<name>/{smoke,dev,test}.jsonl
docs/        ARCHITECTURE.md (source of truth), adr/, OPERATIONS.md, RESULTS.md
scripts/     e2e_smoke.sh, run_eval.py
```

---

## Contributing & security

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, the check gate, PR expectations
- [`SECURITY.md`](SECURITY.md) — supported versions and how to report a vulnerability
- [`CHANGELOG.md`](CHANGELOG.md) — Keep a Changelog + SemVer

Licensed under [Apache-2.0](LICENSE).
