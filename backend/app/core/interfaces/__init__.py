"""Provider and infrastructure interfaces (docs/ARCHITECTURE.md §3.2, §13, §16, §17).

These ``Protocol`` classes fix the architectural boundaries. Concrete adapters live
in ``app/providers`` (LLM / embeddings / reranker) and ``app/infra`` (vector store,
object storage, job queue) and are wired by configuration in their respective phases:

    embeddings  -> Phase 3        vector store  -> Phase 3
    reranker    -> Phase 5        object storage / parser / job queue -> Phase 2
    llm         -> Phase 6
"""
