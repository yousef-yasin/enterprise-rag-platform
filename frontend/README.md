# frontend

Vite + React 18 + TypeScript (strict) SPA for the Enterprise RAG Platform
(docs/ARCHITECTURE.md §24).

## Develop

```bash
npm install
npm run dev          # http://127.0.0.1:5173, proxies /api + /health to :8000
```

Point the proxy elsewhere with `VITE_API_PROXY=http://host:port npm run dev`.

## Checks

| command | what |
|---|---|
| `npm run typecheck` | `tsc --noEmit`, strict |
| `npm run lint` | ESLint, `react/no-danger` = error (§24.2) |
| `npm run test` | Vitest — markdown sanitizer security suite |
| `npm run build` | type-check + production build to `dist/` |
| `npm run e2e` | Playwright golden flow — run `npx playwright install chromium` once; needs a running stack (spawns `vite dev` unless `E2E_BASE_URL` is set) |
| `npm run gen:api` | regenerate `src/api/schema.d.ts` from the live OpenAPI doc |

## Layout

```
src/
  api/        client.ts (fetch + refresh + SSE), endpoints.ts, types.ts
  hooks/      useChatStream (fetch ReadableStream, not EventSource), useJobStatus
  stores/     auth (access token in memory), ui (active KB / conversation)
  lib/        markdown.ts — markdown-it html:false + allowlist sanitizer + [[n]] chips
  components/ Layout, Markdown, CitationPanel, FeedbackButtons, UploadDropzone, …
  pages/      Login, KnowledgeBases, KnowledgeBaseDetail, Documents, Chat, Evaluation, Settings
tests/e2e/    golden.spec.ts
```

## Security

Model output and retrieved document text are untrusted (§24.2). Answers are
rendered by appending a sanitized `DocumentFragment` — never
`dangerouslySetInnerHTML`. Image markdown is disabled and shown inert; links are
restricted to `http/https/mailto` with forced `rel`/`target`. The production CSP
(`connect-src 'self'`, `img-src 'self' data:`, `frame-ancestors 'none'`, …) is
served by nginx (`nginx.conf`).

**Sessions**: the access token is kept in memory only (`stores/auth`). The
refresh token is an `HttpOnly` cookie the browser manages — it is never read by
JS. `client.ts` sends `credentials: "include"` and, for non-GET requests, an
`X-CSRF-Token` header read from the `rag_csrf` companion cookie. On load,
`bootstrap()` calls `POST /auth/refresh` to restore the session from the cookie.
