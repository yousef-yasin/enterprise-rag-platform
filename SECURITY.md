# Security Policy

## Supported versions

This project is pre-1.0. Security fixes are applied to `main` and the latest
tagged release only.

| Version | Supported |
|---|---|
| `main` | ✅ |
| latest `0.x` tag | ✅ |
| older | ❌ |

## Reporting a vulnerability

**Do not open a public issue for security problems.**

Use GitHub's private vulnerability reporting:
**Security → Report a vulnerability** on the repository. If that is unavailable,
open a minimal placeholder issue asking a maintainer to open a private advisory —
without details.

Please include:

- affected component and version / commit
- a description of the impact and the class of vulnerability
- the minimal steps or conditions to reproduce (no working exploit or data-
  extraction walkthrough is required or wanted)

You can expect an acknowledgement within **3 business days** and a triage
assessment within **10 business days**. Coordinated disclosure is appreciated;
we will agree on a timeline with you and credit you in the advisory unless you
prefer otherwise.

## Scope

In scope: the backend API and worker, the ingestion/parsing path, the retrieval
and generation pipeline, the auth/RBAC model, the frontend, the Docker Compose
deployment, and CI/release workflows in this repository.

Out of scope: vulnerabilities in third-party services you point the platform at
(your LLM provider, your managed Postgres, etc.), and findings that require a
already-compromised host or a malicious administrator.

## Security model — quick reference

- **Untrusted inputs** are uploaded documents, retrieved chunk text, and model
  output. The parser enforces type/size/zip-bomb/XXE limits
  ([`ARCHITECTURE.md` §30](docs/ARCHITECTURE.md)); prompts are spotlighted and
  context is fenced; the frontend renders answers through an allowlist sanitizer
  with a strict CSP and never uses `dangerouslySetInnerHTML` (§24.2).
- **Isolation** is the knowledge-base + membership boundary. A non-member gets
  `404`, not `403`. Retrieval sets the KB filter server-side; the client cannot
  widen scope.
- **Sessions**: the access token is returned in the response body and held only
  in browser memory. The refresh token is an `HttpOnly`, `SameSite=Lax` cookie
  scoped to `/api/v1/auth` (`Secure` is required in production and enforced for
  `APP_PROFILE=prod`). `/auth/refresh` and `/auth/logout` require a CSRF
  double-submit token (`X-CSRF-Token` header echoing the non-HttpOnly `rag_csrf`
  cookie). Every other endpoint authenticates with the `Authorization: Bearer`
  header only, so it is not cookie-CSRF-exposed. There is no refresh-token
  denylist in v1 (§25) — a leaked refresh token is valid until it expires.
- **Secrets** never appear in logs (a structlog processor redacts them) or in
  evaluation config snapshots (allowlist only).
- Prompt injection is documented as a *mitigation, not elimination* (§29).
