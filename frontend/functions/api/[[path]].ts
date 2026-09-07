// Cloudflare Pages Function — same-origin API proxy.
//
// The browser only ever talks to the Pages domain (e.g. https://myapp.pages.dev).
// This forwards every /api/* request to the Cloud Run backend unmodified —
// method, headers, body, and response (status, headers, streamed body) pass
// straight through with no buffering. This is the hosted-deployment equivalent
// of frontend/nginx.conf's `location /api/` + SSE `proxy_buffering off` rules
// used by docker-compose; see docs/DEPLOYMENT_ARCHITECTURE.md.
//
// Why this matters: the app's refresh-token cookie is HttpOnly + scoped by the
// browser to whatever origin issued it, and CSRF uses a double-submit cookie
// (docs/ARCHITECTURE.md §24.2). Calling Cloud Run directly from the browser
// would put the API on a different origin than the frontend, breaking both.
// Proxying through Pages keeps everything same-origin so cookies and CSRF work
// exactly as they do in local dev (frontend/vite.config.ts's dev-server proxy)
// and in the docker-compose deployment (nginx) — no code change needed there.
//
// Config: set BACKEND_ORIGIN in the Cloudflare Pages project's environment
// variables to the Cloud Run service URL, e.g.
//   https://erp-api-xxxxxxxxxx-uc.a.run.app   (no trailing slash)

interface Env {
  BACKEND_ORIGIN: string;
}

// Hop-by-hop headers must not be forwarded (fetch also rejects setting some of
// these directly); Cloudflare's edge already manages them for both legs.
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
]);

function filteredHeaders(source: Headers): Headers {
  const out = new Headers();
  for (const [key, value] of source.entries()) {
    if (!HOP_BY_HOP.has(key.toLowerCase())) out.append(key, value);
  }
  return out;
}

export const onRequest: PagesFunction<Env> = async ({ request, env }) => {
  const backendOrigin = env.BACKEND_ORIGIN?.replace(/\/+$/, "");
  if (!backendOrigin) {
    return new Response("Server misconfiguration: BACKEND_ORIGIN is not set.", { status: 500 });
  }

  const url = new URL(request.url);
  const upstreamUrl = `${backendOrigin}${url.pathname}${url.search}`;

  const headers = filteredHeaders(request.headers);
  headers.set("x-forwarded-proto", "https");
  headers.set("x-forwarded-host", url.host);
  const clientIp = request.headers.get("cf-connecting-ip");
  if (clientIp) headers.set("x-forwarded-for", clientIp);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const upstreamResponse = await fetch(upstreamUrl, {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    redirect: "manual",
  });

  // Stream the upstream response straight through — no buffering, so the
  // chat endpoint's SSE frames (tokens, citations) still arrive incrementally.
  // Response headers (Set-Cookie included) and the status code pass through
  // unchanged; the browser sees exactly what Cloud Run returned.
  return new Response(upstreamResponse.body, {
    status: upstreamResponse.status,
    statusText: upstreamResponse.statusText,
    headers: filteredHeaders(upstreamResponse.headers),
  });
};
