# ADR 0004 — fastembed (ONNX) as the default embedding/rerank runtime

- Status: accepted
- Date: 2026-09-03

## Context

The zero-configuration promise is "clone, `docker compose up`, use it." The first
draft made `sentence-transformers` the default local embedding runtime. That pulls
**PyTorch**: the CPU wheel is ~200 MB and, unpinned, `pip` can resolve the CUDA build
(~2.5 GB). Combined with the model download at first boot, the "quick start" became a
10–20 minute, multi-GB, occasionally-OOM experience — and it silently required
internet on first run.

## Decision

Default embedding **and** cross-encoder reranking run on **fastembed** (ONNX Runtime,
CPU). No PyTorch in the default image.

- Dense default: `BAAI/bge-small-en-v1.5` (384-d, ~130 MB ONNX), L2-normalized,
  with the model's query/passage instruction handled by `fastembed`'s
  `query_embed` / `passage_embed`.
- Sparse default: `Qdrant/bm25` (fastembed sparse; term frequencies client-side, IDF
  applied by Qdrant).
- Rerank default (local profile): `Xenova/ms-marco-MiniLM-L-6-v2` cross-encoder
  (~23 M params) via fastembed.
- Model files are cached in a named volume (`modelcache`) and can be **baked into the
  image** for a true offline build.

`sentence-transformers` remains available as an **optional adapter** in a `heavy`
extra / separate image for users who want models fastembed doesn't package.

## Consequences

Positive:
- Default image has no torch; smaller, faster to build, no CUDA/CPU wheel ambiguity.
- ONNX Runtime CPU wheels are well-behaved on linux/amd64 and linux/arm64 (Apple
  Silicon) — pinned explicitly.
- Same runtime for dense, sparse, and rerank — one dependency to reason about.
- "Fully offline" becomes an honest claim when models are baked or pre-cached.

Negative / costs / mitigations:
- fastembed's model catalogue is smaller than the full HF hub. Mitigation: the
  `EmbeddingProvider` / `Reranker` interfaces make adding a `sentence-transformers`
  or hosted adapter a local change; the `heavy` extra exists for this.
- Some newer models land in fastembed later than in `sentence-transformers`.
  Acceptable for a default; power users switch adapters.
- ONNX numerical output can differ slightly from the PyTorch reference. Irrelevant
  for retrieval (cosine ranking is stable); noted so eval snapshots record the
  runtime.

## Alternatives considered

- **sentence-transformers (PyTorch)** as default: rejected for the reasons above;
  kept as an optional adapter.
- **Hosted embeddings only** (OpenAI/Cohere) as default: rejected — breaks the
  offline/local story and forces an API key for the quick start. Hosted embedding
  adapters exist and are first-class for Path A users who want them.
- **llama.cpp / Ollama embeddings** as default: Ollama is already the Path B
  generation runtime, but its embedding models are larger and slower to pull than a
  130 MB ONNX file; kept as an adapter, not the default.
