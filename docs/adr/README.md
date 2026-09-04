# Architecture Decision Records

Short, dated records of decisions that are expensive to reverse or that a reviewer
will reasonably question. Format: Context → Decision → Consequences → Alternatives
considered. Status is one of `accepted`, `superseded by NNNN`, `deprecated`.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-qdrant-vs-pgvector.md) | Qdrant as the vector store (not pgvector) | accepted |
| [0002](0002-arq-vs-celery.md) | arq for background jobs (not Celery / RQ) | accepted |
| [0003](0003-rrf-default-fusion.md) | RRF as the default hybrid-fusion strategy | accepted |
| [0004](0004-fastembed-vs-sentence-transformers.md) | fastembed (ONNX) as the default embedding/rerank runtime | accepted |

New ADRs are numbered sequentially. Superseding an ADR means adding a new one and
flipping the old one's status, not editing history.
