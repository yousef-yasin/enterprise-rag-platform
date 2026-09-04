# seed/

A tiny public-domain corpus loaded into a demo knowledge base when
`SEED_ON_BOOTSTRAP=true` (docs/ARCHITECTURE.md §35), so a fresh `docker compose
up` has something to ask questions about.

- `corpus/` — the documents (Markdown).
- Loaded by `app.cli.seed.seed_corpus`, called from `rag bootstrap`.

It is idempotent: the KB (`slug: demo`) and its documents are created once; a
second bootstrap is a no-op. Not used by the evaluation harness — that has its
own corpus under `eval/`.
