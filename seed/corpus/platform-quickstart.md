# Enterprise RAG Platform — quickstart notes

## Running locally

The stack starts with no `.env` file. Path A uses a hosted LLM and needs one API
key (`LLM_API_KEY`); embeddings and reranking run locally on CPU via ONNX, so no
GPU is required. Path B (`docker compose --profile local up`) runs everything
locally against Ollama.

## Knowledge bases

A knowledge base is the unit of isolation. Every document, chunk, conversation,
and search is scoped to one. Users are added to a knowledge base with a role:

- **viewer** — read documents, chat, leave feedback.
- **editor** — everything a viewer can do, plus upload, reprocess, and delete
  documents.
- **owner** — everything an editor can do, plus manage members, trigger a
  reindex, and delete the knowledge base.

A non-member receives a 404, not a 403, so knowledge-base ids cannot be
enumerated.

## Uploading documents

PDF, DOCX, TXT, and Markdown are supported, up to 25 MB by default. Each upload
is checked by magic bytes, scanned for archive-bomb patterns, and de-duplicated
by content hash. Ingestion runs asynchronously; the document's status moves
through parsing, chunking, and indexing to `ready`. If it fails, the status
becomes `failed` with a specific reason (for example `encrypted` or
`insufficient_text`).

## Asking questions

Chat answers are grounded in the selected knowledge base and cite their sources
with `[[n]]` markers that link to a source panel. If the answer is not in the
corpus, the assistant abstains instead of guessing. Every turn records a
retrieval trace and per-message token and cost accounting.

## API keys

API keys carry scopes (`kb:read`, `kb:ingest`, `kb:manage`, `chat`) that are
intersected with the owning user's memberships — a key can never do more than its
user can, and may be pinned to a single knowledge base.
