# ADR 0001 — Qdrant as the vector store (not pgvector)

- Status: accepted
- Date: 2026-09-03

## Context

The platform needs dense vector search, keyword/BM25-style search, and fusion of the
two, with metadata filtering (knowledge base, document, language) applied at query
time. PostgreSQL is already in the stack for relational data. The obvious "one fewer
service" option is `pgvector`.

## Decision

Use **Qdrant** as the vector store. Keep PostgreSQL as the source of truth for chunk
text and metadata (needed anyway for exact-match lookups and durability).

## Consequences

Positive:
- Native **sparse vectors** with an `IDF` modifier give a BM25-style keyword channel
  in the same store as the dense channel, with the same payload filters.
- **Server-side fusion** (`Query API` with `prefetch` + `FusionQuery`, Qdrant ≥ 1.10)
  for the common RRF path — one round trip, no application-side merge for the default.
- Payload indexes on `knowledge_base_id` / `document_id` / `doc_version` make the
  mandatory security filter cheap.
- Named vectors leave room for a second dense model or late-interaction vectors later
  without a schema break.
- Clean local story: one container, healthcheck on `/readyz`, snapshot API for backup.

Negative / costs:
- One more stateful service to run, back up, and reason about.
- Two-store consistency: a chunk exists in Postgres **and** as a Qdrant point. This
  is handled by an explicit write protocol and a reconciliation job
  (ARCHITECTURE.md §9), which is real work we would not need with pgvector.
- Qdrant is the one component in the stack without a trivial in-repo substitute.
  Mitigated by the `VectorStore` interface; a `pgvector` adapter is possible but
  would not reach sparse+fusion parity without extra effort.

## Alternatives considered

- **pgvector**: fewer services, transactional consistency with the rest of the data.
  Rejected for v1 because hybrid retrieval would need `pg_trgm` / `tsvector` +
  application-side fusion + manual score normalization, and HNSW filtering ergonomics
  are weaker. The whole point of the project is to demonstrate a competent retrieval
  stack; the vector store is not where we cut.
- **Elasticsearch / OpenSearch**: a heavy second stateful service for a capability
  Qdrant + Postgres already cover at this scale. Revisit only under real corpus/QPS
  pressure.
- **Weaviate / Milvus**: comparable capability, heavier local footprint (Milvus) or a
  broader surface than needed (Weaviate). No decisive advantage for this project.
