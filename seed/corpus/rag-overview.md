# Retrieval-Augmented Generation — an overview

## What RAG is

Retrieval-Augmented Generation (RAG) is a pattern for grounding a language model
in an external corpus. Instead of relying only on parameters learned at training
time, the system retrieves relevant passages from a knowledge base at query time
and places them in the model's context window. The model is then asked to answer
using only that provided context, and to cite it.

## Why use it

- **Freshness** — the corpus can be updated without retraining the model.
- **Attribution** — answers point back to specific source passages.
- **Scope control** — the model answers from your documents, not the open web.
- **Smaller models** — a capable retriever lets a smaller generator do well.

## The pipeline

1. **Ingestion** — documents are parsed into a structure-aware block tree, split
   into overlapping chunks sized to the embedding model's limit, embedded, and
   written to a vector store alongside their text in a relational database.
2. **Retrieval** — the query is embedded and used for a dense nearest-neighbour
   search; a sparse keyword search runs in parallel; the two result lists are
   fused (Reciprocal Rank Fusion by default).
3. **Reranking** — a cross-encoder re-scores the top fused candidates for
   relevance to the exact query.
4. **Assembly** — the highest-scoring chunks are packed into the context window
   within a token budget, each tagged with a stable citation id.
5. **Generation** — the model streams an answer that cites the chunks it used.
6. **Abstention** — if retrieval is empty or low-confidence, the system refuses
   rather than guessing.

## Hybrid retrieval

Dense retrieval captures meaning: "time off policy" can match a passage about
"annual leave". Sparse retrieval captures exact terms: product names, error
codes, and rare tokens that an embedding may smooth over. Running both and fusing
the results is more robust than either alone.

## Evaluation

RAG quality is measured on a labelled dataset: retrieval metrics (recall@k,
nDCG@k), answer correctness and faithfulness (often via an LLM judge), citation
precision and recall, and abstention precision and recall on unanswerable
questions. Aggregates should carry confidence intervals so that improvements are
distinguishable from noise.
