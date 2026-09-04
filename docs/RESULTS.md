# Results

Reproducible evaluation results for the retrieval + generation pipeline
(docs/ARCHITECTURE.md §33).

> **Status.** The committed `smoke` split runs in CI on every push with **fake,
> deterministic providers** — it verifies the harness end to end, not answer
> quality. The numbers below are placeholders until a run with real providers on
> the `test` split is recorded here. The methodology and commands are final.

## Methodology

- **Corpus:** `eval/corpus/handbook/` (2 short public-domain policy documents),
  ingested into one knowledge base with the default chunk policy.
- **Dataset:** `eval/datasets/handbook/<split>.jsonl` — labelled questions with
  reference answers, `relevant_doc_names`, and `should_abstain` flags (6 in
  `smoke`, 10 in `dev`). A `test` split is added when real-provider numbers are
  recorded.
- **Config:** `redacted_config()` snapshot is stored on every `eval_runs` row.
  The runs below use `RETRIEVAL__FUSION_STRATEGY=rrf`, cross-encoder reranking,
  `RERANK_OUTPUT_K=8`.
- **Judge:** a separate model family from the system under test (a
  same-family judge triggers a recorded `_judge_family_warning`).
- **CIs:** non-parametric bootstrap, `EVAL_BOOTSTRAP_N=1000`, 95% percentile
  interval, `nan` samples dropped.

## Commands

```bash
# 1. ingest the corpus into a KB (see eval/README.md), note the KB uuid
# 2. run
cd backend
uv run rag eval run handbook --kb <kb-uuid> --split test --label "rrf+rerank"

# 3. an ablation (no reranker)
RERANKER=none uv run rag eval run handbook --kb <kb-uuid> --split test --label "rrf-only"

# 4. compare with bootstrap difference CIs
uv run rag eval compare <run-rrf+rerank> <run-rrf-only>
```

## Retrieval quality (`test` split)

| config | recall@8 | nDCG@8 | MRR | hit@8 |
|---|---|---|---|---|
| dense only | _tbd_ | _tbd_ | _tbd_ | _tbd_ |
| hybrid (RRF), no rerank | _tbd_ | _tbd_ | _tbd_ | _tbd_ |
| hybrid (RRF) + cross-encoder | _tbd_ | _tbd_ | _tbd_ | _tbd_ |

## Answer quality (`test` split)

| metric | value (95% CI) |
|---|---|
| judge correctness | _tbd_ |
| judge faithfulness | _tbd_ |
| answer token-F1 | _tbd_ |
| citation precision | _tbd_ |
| citation recall | _tbd_ |
| citation ⊆ context (hard) | _tbd_ |

## Abstention (`test` split)

| metric | value |
|---|---|
| abstention precision | _tbd_ |
| abstention recall | _tbd_ |
| abstention F1 | _tbd_ |

## Cost & latency (`test` split, per question)

| metric | value (95% CI) |
|---|---|
| prompt tokens | _tbd_ |
| completion tokens | _tbd_ |
| USD / question | _tbd_ |
| end-to-end latency | _tbd_ |

## Ablations to report

1. fusion strategy: `rrf` vs `weighted_norm` vs `dbsf`
2. reranker: `none` vs `fastembed_cross_encoder`
3. query rewriting on vs off (multi-turn subset)
4. `RERANK_OUTPUT_K` sweep (context size vs faithfulness/cost)
