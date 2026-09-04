# eval/

Offline evaluation datasets and corpora for the RAG pipeline
(docs/ARCHITECTURE.md §33).

```
eval/
  corpus/<name>/*.md        documents to ingest into a KB before a run
  datasets/<name>/<split>.jsonl   labelled questions
```

## Dataset format (JSONL, one object per line)

| field | type | meaning |
|---|---|---|
| `question` | string | the user question (required) |
| `answer` | string? | reference answer — enables `answer_token_f1` and grounds the judge |
| `relevant_doc_names` | string[]? | filenames that should be retrieved — enables `recall@k`, `precision@k`, `mrr`, `ndcg@k`, `hit@k` (document-level) |
| `relevant_chunk_ids` | string[]? | exact gold chunk ids (chunk-level retrieval metrics) |
| `supporting_chunk_ids` | string[]? | gold chunks used for citation precision/recall |
| `should_abstain` | bool? | the system *should* refuse (no answer in the corpus) — feeds abstention precision/recall |

`#`-prefixed and blank lines are ignored.

## Running

```bash
# 1. create a KB and ingest the corpus (once)
rag user create --email you@example.com --admin
#    ... create a KB in the UI or via the API, upload eval/corpus/<name>/* ...

# 2. run
rag eval run <name> --kb <kb-uuid> --split smoke
rag eval run <name> --kb <kb-uuid> --split dev --label "rrf+rerank"

# 3. compare two runs with bootstrap difference CIs
rag eval compare <run-a> <run-b>

# 4. calibrate the reranker abstention threshold from a labelled dev split
rag eval calibrate-reranker --kb <kb-uuid> --dataset <name> --split dev
```

The `smoke` split is what CI runs (fake providers, `APP_PROFILE=ci`) — it checks
the harness end to end, not answer quality.
