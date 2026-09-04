// DTOs mirroring backend/app/schemas/*. `npm run gen:api` regenerates
// src/api/schema.d.ts from the live OpenAPI doc; CI diffs the two (drift check).

export type KBRole = "owner" | "editor" | "viewer";
export type ApiKeyScope = "kb:read" | "kb:ingest" | "kb:manage" | "chat";
export type RetrievalMode = "dense" | "sparse" | "hybrid";
// backend/app/core/enums.py::DocumentStatus — single `processing` status with a
// `failed_stage` field, not per-phase statuses.
export type DocumentStatus =
  | "pending"
  | "processing"
  | "ready"
  | "partially_indexed"
  | "failed";

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
  request_id?: string;
}

export interface Page<T> {
  items: T[];
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
}

export interface KnowledgeBase {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  owner_id: string;
  active_embedding_profile_id: string | null;
  your_role: KBRole;
  created_at: string;
}

export interface Member {
  user_id: string;
  email: string;
  display_name: string;
  role: KBRole;
  added_at: string;
}

export interface DocumentModel {
  id: string;
  knowledge_base_id: string;
  filename: string;
  mime: string;
  size_bytes: number;
  page_count: number | null;
  lang: string | null;
  language_warning: boolean;
  status: DocumentStatus;
  failed_stage: string | null;
  failure_reason: string | null;
  active_index_version: number | null;
  content_hash: string;
  created_at: string;
  indexed_at: string | null;
}

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  knowledge_base_id: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKey {
  token: string;
}

export interface SearchHit {
  chunk_id: string;
  document_id: string;
  score: number;
  filename: string;
  page_no: number | null;
  snippet: string;
  section_path: string[];
}

export interface SearchResponse {
  search_query: string;
  mode: RetrievalMode;
  hits: SearchHit[];
  abstained: boolean;
  low_confidence: boolean;
  degraded: Record<string, boolean>;
  fusion_strategy: string;
  trace: Record<string, unknown> | null;
}

export interface Citation {
  index: number;
  chunk_id: string | null;
  document_id: string | null;
  filename: string;
  page_no: number | null;
  snippet: string;
  was_cited: boolean;
  weak: boolean;
  score: number | null;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  conversation_id: string | null;
  message_id: string | null;
  trace_id: string | null;
  abstained: boolean;
  low_confidence: boolean;
  degraded: Record<string, boolean>;
  uncited_sentences: string[];
  usage: { prompt_tokens: number; completion_tokens: number };
  cost_usd: number;
}

export interface Conversation {
  id: string;
  knowledge_base_id: string;
  title: string;
  archived: boolean;
  total_tokens: number;
  total_cost_usd: number;
  created_at: string;
}

export interface MessageCitation {
  citation_index: number;
  document_filename: string | null;
  was_cited: boolean;
  weak: boolean;
  snippet: string | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  model: string | null;
  abstained: boolean;
  low_confidence: boolean;
  created_at: string;
  citations: MessageCitation[];
}

// SSE `done` payload from POST /chat/stream (services/chat.py answer()).
export interface ChatStreamDone {
  answer: string;
  citations: Citation[];
  abstained: boolean;
  low_confidence: boolean;
  degraded: Record<string, boolean>;
  uncited_sentences?: string[];
  trace_id: string | null;
  conversation_id: string | null;
  message_id: string | null;
  usage: { prompt_tokens: number; completion_tokens: number };
  cost_usd: number;
}

export interface EvalRunSummary {
  id: string;
  dataset: string;
  split: string;
  status: string;
  git_sha: string | null;
  config_label: string | null;
  n_samples: number;
  metrics: Record<string, EvalMetric>;
  created_at: string;
  completed_at: string | null;
}

export interface EvalMetric {
  value: number;
  ci_low?: number;
  ci_high?: number;
  n?: number;
}
