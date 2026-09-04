"""Provider adapters (docs/ARCHITECTURE.md §3.2, §4.1).

Concrete implementations of the ``app.core.interfaces`` protocols plus a
configuration-driven ``registry`` that lazily imports the selected one. Nothing here
yet — adapters and the registry land with their features:

    embeddings/  (fastembed, openai, ollama, fake)   -> Phase 3
    rerank/      (fastembed_cross_encoder, cohere, jina, noop) -> Phase 5
    llm/         (openai, anthropic, ollama, fake)    -> Phase 6

The runtime safety rule "no fake providers outside APP_PROFILE ci/test" is enforced
now by :func:`app.config.validate_consistency`; the registry will re-assert it.
"""
