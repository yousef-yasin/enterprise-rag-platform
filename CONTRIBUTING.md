# Contributing

Thanks for considering a contribution. This project aims to be a credible,
maintainable reference implementation — changes are held to that bar.

## Ground rules

- **`docs/ARCHITECTURE.md` (Revision 2) is the source of truth.** Behavioural or
  structural changes that contradict it need an ADR in `docs/adr/` first, or a
  PR that updates the architecture doc as part of the change.
- Keep the layering: `api → services → core / providers / infra`. `core` is pure
  (no I/O); providers are the only place concrete SDKs are imported; `config` is
  the only place environment is read.
- **Fake providers are test/CI only.** They must never be reachable in a runtime
  profile — `app.config.validate_consistency` enforces this; don't weaken it.
- No `torch` in the default dependency set. Local models go through `fastembed`
  (ONNX). Heavy optional backends live under the `heavy` extra.

## Dev setup

```bash
# backend (needs uv: https://docs.astral.sh/uv/)
cd backend && uv sync

# infra for integration tests
docker compose -f compose.test.yml up -d --wait

# frontend
cd frontend && npm install
```

## The check gate

Every PR must pass, locally and in CI:

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy                                   # strict, zero errors
uv run pytest tests/unit
RAG_INTEGRATION=1 APP_PROFILE=ci LLM_PROVIDER=fake EMBEDDING_PROVIDER=fake \
  POSTGRES_HOST=127.0.0.1 QDRANT_URL=http://127.0.0.1:6333 REDIS_HOST=127.0.0.1 \
  uv run pytest tests/integration

cd ../frontend
npm run lint && npm run typecheck && npm run test && npm run build
```

`make check` runs the backend half. New behaviour needs tests; new config needs a
default and an entry in `.env.example`.

## Database changes

Model change → `cd backend && uv run alembic revision --autogenerate -m "…"` →
review the migration by hand → confirm `uv run alembic check` is clean and that
`upgrade` / `downgrade` / `upgrade` round-trips on a populated DB
(`tests/integration/test_migrations.py` does this in CI).

## Commits & PRs

- Conventional-ish subject lines (`feat:`, `fix:`, `docs:`, `refactor:`…), imperative mood.
- One logical change per PR. Explain the *why* in the description; link the ADR or
  architecture section if relevant.
- Update `CHANGELOG.md` under `## [Unreleased]`.

## Reporting security issues

See [`SECURITY.md`](SECURITY.md) — not the public issue tracker.
