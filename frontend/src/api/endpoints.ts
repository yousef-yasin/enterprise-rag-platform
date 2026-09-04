import { request } from "./client";
import type {
  ApiKey,
  ApiKeyCreated,
  ApiKeyScope,
  ChatResponse,
  Conversation,
  DocumentModel,
  DocumentStatus,
  EvalRunSummary,
  KBRole,
  KnowledgeBase,
  Member,
  Message,
  Page,
  RetrievalMode,
  SearchResponse,
  TokenResponse,
  User,
} from "./types";

export const auth = {
  login: (email: string, password: string) =>
    request<TokenResponse>("/auth/login", { method: "POST", body: { email, password } }),
  register: (email: string, password: string, display_name: string, make_admin = false) =>
    request<User>("/auth/register", {
      method: "POST",
      body: { email, password, display_name, make_admin },
    }),
  me: () => request<User>("/auth/me"),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
};

export const kbs = {
  list: () => request<Page<KnowledgeBase>>("/knowledge-bases", { query: { limit: 100 } }),
  get: (id: string) => request<KnowledgeBase>(`/knowledge-bases/${id}`),
  create: (name: string, slug: string, description?: string) =>
    request<KnowledgeBase>("/knowledge-bases", {
      method: "POST",
      body: { name, slug, description: description || null },
    }),
  update: (id: string, body: { name?: string; description?: string }) =>
    request<KnowledgeBase>(`/knowledge-bases/${id}`, { method: "PATCH", body }),
  remove: (id: string) => request<void>(`/knowledge-bases/${id}`, { method: "DELETE" }),
  members: (id: string) => request<Member[]>(`/knowledge-bases/${id}/members`),
  addMember: (id: string, email: string, role: Exclude<KBRole, "owner">) =>
    request<Member>(`/knowledge-bases/${id}/members`, { method: "POST", body: { email, role } }),
  removeMember: (id: string, userId: string) =>
    request<void>(`/knowledge-bases/${id}/members/${userId}`, { method: "DELETE" }),
};

export const documents = {
  list: (kbId: string, status?: DocumentStatus) =>
    request<Page<DocumentModel>>(`/knowledge-bases/${kbId}/documents`, {
      query: { limit: 100, status },
    }),
  get: (id: string) => request<DocumentModel>(`/documents/${id}`),
  upload: (kbId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentModel>(`/knowledge-bases/${kbId}/documents`, { method: "POST", form });
  },
  reprocess: (id: string) =>
    request<DocumentModel>(`/documents/${id}/reprocess`, { method: "POST" }),
  remove: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  statusStreamPath: (id: string) => `/api/v1/documents/${id}/status/stream`,
};

export const apiKeys = {
  list: () => request<ApiKey[]>("/api-keys"),
  create: (name: string, scopes: ApiKeyScope[], knowledge_base_id?: string) =>
    request<ApiKeyCreated>("/api-keys", {
      method: "POST",
      body: { name, scopes, knowledge_base_id: knowledge_base_id || null },
    }),
  revoke: (id: string) => request<void>(`/api-keys/${id}`, { method: "DELETE" }),
};

export const search = {
  query: (
    knowledge_base_id: string,
    query: string,
    mode: RetrievalMode,
    include_trace = false,
  ) =>
    request<SearchResponse>("/search", {
      method: "POST",
      body: { knowledge_base_id, query, params: { mode }, include_trace },
    }),
};

export const chat = {
  send: (
    knowledge_base_id: string,
    message: string,
    conversation_id: string | null,
    mode: RetrievalMode,
  ) =>
    request<ChatResponse>("/chat", {
      method: "POST",
      body: { knowledge_base_id, message, conversation_id, params: { mode } },
    }),
};

export const conversations = {
  list: () => request<Page<Conversation>>("/conversations", { query: { limit: 100 } }),
  messages: (id: string) =>
    request<Page<Message>>(`/conversations/${id}`, { query: { limit: 100 } }),
  rename: (id: string, title: string) =>
    request<Conversation>(`/conversations/${id}`, { method: "PATCH", body: { title } }),
  remove: (id: string) => request<void>(`/conversations/${id}`, { method: "DELETE" }),
  feedback: (messageId: string, rating: "up" | "down", reason?: string, comment?: string) =>
    request<void>(`/messages/${messageId}/feedback`, {
      method: "POST",
      body: { rating, reason: reason || null, comment: comment || null },
    }),
};

export const evaluation = {
  runs: () => request<Page<EvalRunSummary>>("/eval/runs", { query: { limit: 50 } }),
  run: (id: string) => request<EvalRunSummary>(`/eval/runs/${id}`),
};
