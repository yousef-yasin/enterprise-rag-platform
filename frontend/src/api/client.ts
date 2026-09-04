import type { ApiError } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "";
const API = `${BASE}/api/v1`;
const CSRF_COOKIE = "rag_csrf";
const CSRF_HEADER = "x-csrf-token";

export class RequestError extends Error {
  status: number;
  code: string;
  details?: unknown;
  requestId?: string;
  constructor(status: number, body: ApiError) {
    super(body.message || `request failed (${status})`);
    this.name = "RequestError";
    this.status = status;
    this.code = body.code || "error";
    this.details = body.details;
    this.requestId = body.request_id;
  }
}

// The access token lives only in memory (§24.2). The refresh token is an
// HttpOnly cookie the browser sends automatically to /api/v1/auth/* — it is
// never visible here. Session state survives a reload via the cookie: `bootstrap`
// calls `refreshSession()` on start.
let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}
export function currentAccessToken(): string | null {
  return accessToken;
}
export function clearSession(): void {
  accessToken = null;
}

/** Reads the non-HttpOnly CSRF companion cookie for the double-submit check. */
export function getCsrfToken(): string | null {
  try {
    for (const part of document.cookie.split(";")) {
      const [name, ...rest] = part.trim().split("=");
      if (name === CSRF_COOKIE) return decodeURIComponent(rest.join("="));
    }
  } catch {
    /* document unavailable */
  }
  return null;
}

interface AccessTokenBody {
  access_token: string;
  token_type: string;
}

let refreshInFlight: Promise<boolean> | null = null;

/** POST /auth/refresh using the HttpOnly cookie + CSRF header. */
export async function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const csrf = getCsrfToken();
        const res = await fetch(`${API}/auth/refresh`, {
          method: "POST",
          credentials: "include",
          headers: csrf ? { [CSRF_HEADER]: csrf } : {},
        });
        if (!res.ok) {
          clearSession();
          return false;
        }
        const body = (await res.json()) as AccessTokenBody;
        accessToken = body.access_token;
        return true;
      } catch {
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

interface Options {
  method?: string;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | undefined>;
  retryOn401?: boolean;
}

function buildUrl(path: string, query?: Options["query"]): string {
  const url = new URL(`${API}${path}`, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined) url.searchParams.set(k, String(v));
    }
  }
  return url.toString();
}

function authHeaders(method: string): Record<string, string> {
  const headers: Record<string, string> = {};
  if (accessToken) headers.authorization = `Bearer ${accessToken}`;
  if (method !== "GET" && method !== "HEAD") {
    const csrf = getCsrfToken();
    if (csrf) headers[CSRF_HEADER] = csrf; // harmless where unused; required by /auth/*
  }
  return headers;
}

export async function request<T>(path: string, opts: Options = {}): Promise<T> {
  const { method = "GET", body, form, signal, query, retryOn401 = true } = opts;
  const headers = authHeaders(method);
  if (body !== undefined) headers["content-type"] = "application/json";

  const res = await fetch(buildUrl(path, query), {
    method,
    headers,
    credentials: "include",
    body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    signal,
  });

  if (res.status === 401 && retryOn401 && (await refreshSession())) {
    return request<T>(path, { ...opts, retryOn401: false });
  }

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  const payload: unknown = text ? JSON.parse(text) : {};

  if (!res.ok) {
    const err = (payload as { error?: ApiError }).error ?? {
      code: "error",
      message: `request failed (${res.status})`,
    };
    if (res.status === 401) clearSession();
    throw new RequestError(res.status, err);
  }
  return payload as T;
}

// Streaming (SSE) — fetch + ReadableStream so the Authorization header works
// (EventSource cannot set headers, §23.2). Yields parsed `event: <type>` frames.
export interface SseFrame {
  event: string;
  data: unknown;
}

export async function* streamSse(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<SseFrame> {
  const doFetch = () =>
    fetch(buildUrl(path), {
      method: "POST",
      credentials: "include",
      headers: {
        "content-type": "application/json",
        ...authHeaders("POST"),
      },
      body: JSON.stringify(body),
      signal,
    });

  let res = await doFetch();
  if (res.status === 401 && (await refreshSession())) res = await doFetch();
  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    const err = (safeParse(text) as { error?: ApiError })?.error ?? {
      code: "error",
      message: `stream failed (${res.status})`,
    };
    throw new RequestError(res.status, err);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const raw = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      let event = "message";
      const dataLines: string[] = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length) yield { event, data: safeParse(dataLines.join("\n")) };
    }
  }
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export { API as apiBase };
