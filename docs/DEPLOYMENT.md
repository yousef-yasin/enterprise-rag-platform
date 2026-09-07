# Deployment — free public demo

Step-by-step instructions for deploying enterprise-rag-platform publicly on
free-tier infrastructure. See [`DEPLOYMENT_ARCHITECTURE.md`](DEPLOYMENT_ARCHITECTURE.md)
for the diagram and the reasoning behind each choice, and
[`OPERATIONS.md`](OPERATIONS.md) for running the existing docker-compose
deployment (still fully supported, unchanged).

**Nothing in this document has been executed against real cloud accounts as
part of preparing it.** Every command below was checked against the actual
code in this repository (settings names, CLI commands, health endpoints) and,
where it doesn't require a cloud account, actually run and verified locally
(the `Dockerfile.cloudrun` build, the health endpoints, the Pages Function's
type-check). The commands that do need your own Neon/Qdrant Cloud/Upstash/
Cloudflare/GCP accounts are documented but **unexecuted and unverified
end-to-end** — you will be the first to run them for real. Treat this as a
precise, audited runbook, not a claim that a public URL already exists.

## Prerequisites

- A Google Cloud project with billing enabled (Cloud Run's free tier still
  requires a billing account attached; you are not charged unless you exceed
  it — see *Costs* below).
- `gcloud` CLI and Docker installed locally.
- Free accounts: [Neon](https://neon.tech), [Qdrant Cloud](https://cloud.qdrant.io),
  [Upstash](https://upstash.com), [Cloudflare](https://dash.cloudflare.com)
  (Pages + R2), and a [Gemini API key](https://ai.google.dev/).
- This repo cloned locally.

## 1. Neon PostgreSQL

1. Create a free Neon project + database.
2. Copy the connection string Neon gives you — it looks like:
   `postgresql://<user>:<password>@<endpoint>.neon.tech/<dbname>?sslmode=require`
3. That whole string is your `DATABASE_URL`. The app's asyncpg driver parses
   `sslmode` natively from the URL — no separate SSL flag needed
   (`app/config.py`'s `_to_asyncpg_url`, added for this deployment, just
   swaps the URL scheme to `postgresql+asyncpg://` and leaves the rest as-is).

## 2. Qdrant Cloud

1. Create a free cluster at cloud.qdrant.io.
2. Copy the cluster URL (`https://xxxxxxxx.<region>.aws.cloud.qdrant.io:6333`)
   and the API key.
3. Set `QDRANT_URL` and `QDRANT_API_KEY`. No manual collection setup is
   needed — `app/infra/qdrant/bootstrap.py`'s `ensure_collection` creates each
   knowledge base's collection lazily, idempotently, the first time it's
   ingested into (advisory-locked so concurrent requests don't race).

## 3. Upstash Redis

1. Create a free Redis database (choose the "Global" or regional type; TLS is
   on by default).
2. Copy the `rediss://` connection string Upstash gives you.
3. Set `REDIS_URL` to that string. This app's Redis usage (`app/config.py`'s
   `redis_dsn`, and every call site in `app/infra/redis/`, `app/workers/`)
   was extended for this deployment to accept a full URL — including TLS
   (`rediss://`) — instead of only discrete host/port/password fields, since
   Upstash requires TLS and the previous discrete fields couldn't express it.

## 4. Cloudflare R2 (object storage)

Cloud Run's container filesystem does not persist across restarts or
instances, so uploaded documents cannot live on local disk in this
deployment. The app's existing S3-compatible storage backend
(`app/infra/storage/s3.py`) works with R2 unmodified — R2 speaks the S3 API.

1. Create an R2 bucket in the Cloudflare dashboard.
2. Create an R2 API token (Account → R2 → Manage API Tokens) with read/write
   access to that bucket. Note the **Access Key ID**, **Secret Access Key**,
   and your **Account ID**.
3. Set:
   ```
   STORAGE_BACKEND=s3
   S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
   S3_BUCKET=<your-bucket-name>
   S3_ACCESS_KEY=<r2-access-key-id>
   S3_SECRET_KEY=<r2-secret-access-key>
   S3_REGION=auto
   ```
   (`S3_REGION` defaults to `us-east-1` in `app/config.py`, which R2 also
   accepts, but Cloudflare's own docs recommend `auto`.)

## 5. Gemini API key

Get a key at [ai.google.dev](https://ai.google.dev/). Set:

```
LLM_PROVIDER=openai
LLM_MODEL=gemini-2.5-flash
LLM_API_KEY=<your-gemini-api-key>
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
```

This is the repository's **existing** OpenAI-compatible provider
(`app/providers/llm/openai_provider.py`) pointed at Gemini's OpenAI-compatible
endpoint — no Gemini-specific code exists or is needed. This exact
configuration was already manually verified end-to-end (real Gemini 2.5
Flash, real citations, real abstention) before this deployment work started.

Embeddings and the reranker stay on their CPU-only defaults
(`EMBEDDING_PROVIDER=fastembed`, `RERANKER=fastembed_cross_encoder`) — local
ONNX models, no GPU, no separate API key. `Dockerfile.cloudrun` pre-downloads
both models at build time (see below) so a cold Cloud Run instance doesn't
fetch them on its first request.

## 6. Build the Cloud Run image

`backend/Dockerfile.cloudrun` is a separate file from `backend/Dockerfile`
(which docker-compose still uses, unchanged) — Cloud Run needs `$PORT`
support, no dev reload, the `s3` extra installed (for R2), and pre-baked
embedding/reranker models; `./Dockerfile` intentionally doesn't carry any of
that.

```bash
gcloud auth login
gcloud config set project PROJECT_ID

REGION=us-central1
gcloud auth configure-docker "${REGION}-docker.pkg.dev"
gcloud artifacts repositories create erp \
  --repository-format=docker --location="$REGION"   # once, if it doesn't exist

IMAGE="${REGION}-docker.pkg.dev/PROJECT_ID/erp/api:latest"
```

Either build locally and push:

```bash
cd backend
docker build -f Dockerfile.cloudrun -t "$IMAGE" .
docker push "$IMAGE"
```

...or build in Cloud Build (`cloudbuild.yaml` points it at
`Dockerfile.cloudrun`, since `gcloud builds submit` otherwise only looks for a
file literally named `Dockerfile`):

```bash
cd backend
gcloud builds submit --config=cloudbuild.yaml --substitutions=_IMAGE="$IMAGE" .
```

Both were verified locally in this session (`docker build -f
Dockerfile.cloudrun` succeeded, the resulting image starts, binds `$PORT`,
and serves `/health/live`/`/health/ready` correctly — see *Final verification*
in the PR/session notes). The `gcloud builds submit` / `gcloud run deploy`
commands themselves were not run against a real GCP project.

## 7. Run database migrations (once, before or after first deploy)

Migrations are **not** run automatically on every container startup — a
crash-looping instance must never be able to re-run `alembic upgrade head`
unsupervised. Run it once, explicitly, whenever the schema changes:

```bash
docker run --rm \
  -e APP_PROFILE=prod \
  -e DATABASE_URL='postgresql://...neon.tech/...?sslmode=require' \
  -e LLM_PROVIDER=openai -e LLM_API_KEY=dummy-not-used-for-migrations \
  -e JWT_SECRET="$(openssl rand -hex 32)" -e SESSION_COOKIE_SECURE=true \
  "$IMAGE" rag bootstrap
```

`rag bootstrap` (`app/cli/main.py`) runs `alembic upgrade head`, then
idempotently creates the `BOOTSTRAP_ADMIN_EMAIL` admin user if one doesn't
exist yet (add `-e BOOTSTRAP_ADMIN_EMAIL=... -e BOOTSTRAP_ADMIN_PASSWORD=...`
to set one). To run only the migration, without touching the admin user:

```bash
docker run --rm -e DATABASE_URL=... "$IMAGE" \
  python -c "from app.cli.migrations import upgrade_to_head; upgrade_to_head()"
```

Some config validation (a real `LLM_API_KEY`, a strong `JWT_SECRET`, etc.) is
required just to construct `Settings` even for a migration-only run — the
placeholder values above satisfy validation without being used for anything
migrations touch.

## 8. Deploy to Cloud Run

```bash
gcloud run deploy erp-api \
  --image="$IMAGE" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --cpu=1 --memory=1Gi \
  --concurrency=20 \
  --timeout=300 \
  --min-instances=0 --max-instances=3 \
  --set-env-vars="APP_PROFILE=prod,AUTH_MODE=multi_user,LLM_PROVIDER=openai,LLM_MODEL=gemini-2.5-flash,LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/,EMBEDDING_PROVIDER=fastembed,RERANKER=fastembed_cross_encoder,STORAGE_BACKEND=s3,S3_REGION=auto,WORKER_MODE=inline,SESSION_COOKIE_SECURE=true,SESSION_COOKIE_SAMESITE=lax,CORS_ALLOW_ORIGINS=https://YOUR-PROJECT.pages.dev" \
  --set-secrets="LLM_API_KEY=erp-llm-api-key:latest,DATABASE_URL=erp-database-url:latest,REDIS_URL=erp-redis-url:latest,QDRANT_API_KEY=erp-qdrant-api-key:latest,S3_ACCESS_KEY=erp-s3-access-key:latest,S3_SECRET_KEY=erp-s3-secret-key:latest,JWT_SECRET=erp-jwt-secret:latest,BOOTSTRAP_ADMIN_PASSWORD=erp-admin-password:latest"
```

Notes:

- `--allow-unauthenticated` makes the Cloud Run **endpoint** publicly
  reachable — it does not disable this app's own authentication.
  `AUTH_MODE=multi_user` (the default) still requires every API caller to
  register/log in and hold a valid access token or refresh cookie; there is
  no anonymous access to any knowledge base or chat endpoint.
- `--set-secrets` reads from [Secret Manager](https://cloud.google.com/secret-manager) —
  create each secret first (`gcloud secrets create erp-llm-api-key
  --data-file=-` etc.) so no credential is ever passed as a plain
  `--set-env-vars` value or committed anywhere. `QDRANT_URL` and the
  non-secret settings above are fine as plain env vars.
- `--concurrency=20` and `--cpu=1`/`--memory=1Gi` are conservative starting
  points for a small demo running `WORKER_MODE=inline` (each concurrent
  ingestion request does real CPU work — parsing, embedding, reranking — on
  that single vCPU); tune based on what you actually see in Cloud
  Monitoring, not in advance.
- `--timeout=300` (5 minutes) is needed because `WORKER_MODE=inline` makes
  the upload endpoint block until ingestion finishes — see
  `DEPLOYMENT_ARCHITECTURE.md`. Raise it further for larger documents;
  Cloud Run supports up to 60 minutes.
- `CORS_ALLOW_ORIGINS` should be your **exact** Cloudflare Pages production
  URL. Since the browser only ever talks to the Pages domain (same-origin
  proxy, below), this mostly guards against someone calling the Cloud Run URL
  directly from a browser page on another origin with credentials — it is
  not the primary security boundary, but keep it exact and non-wildcard
  regardless (`app/main.py` already sets `allow_credentials=True`, so a
  wildcard origin would be rejected by browsers anyway per the CORS spec).

## 9. Cloudflare Pages (frontend + same-origin proxy)

1. In the Cloudflare dashboard: Pages → Create project → connect this repo.
2. Build settings:
   - **Build command**: `npm run build`
   - **Build output directory**: `frontend/dist`
   - **Root directory**: `frontend`
3. Environment variables (Pages project settings → Environment variables):
   - `BACKEND_ORIGIN` = your Cloud Run service URL (e.g.
     `https://erp-api-xxxxxxxxxx-uc.a.run.app`, **no trailing slash**) — read
     by `frontend/functions/api/[[path]].ts`, the Pages Function that proxies
     `/api/*` to Cloud Run.
   - Leave `VITE_API_BASE` **unset**. `frontend/src/api/client.ts` defaults
     it to an empty string, so the SPA calls relative `/api/v1/...` paths —
     same origin as the page itself, which the Pages Function then forwards.
4. Deploy. Cloudflare gives you a free `https://<project>.pages.dev` URL —
   this already satisfies "make it work with the free URL"; no custom domain
   is required.
5. Update the Cloud Run service's `CORS_ALLOW_ORIGINS` to that exact
   `https://<project>.pages.dev` URL (step 8), then redeploy the Cloud Run
   revision (`gcloud run services update erp-api --update-env-vars=...`) —
   there's a brief chicken-and-egg here (you need the Pages URL before you
   can lock down CORS to it) that's easiest to resolve by deploying Cloud Run
   once with a permissive placeholder, then tightening it once Pages has
   assigned your `.pages.dev` URL.

The proxy (`functions/api/[[path]].ts`) forwards method, headers, and body
unmodified, and streams the response back without buffering — verified with
`tsc` against real `@cloudflare/workers-types` in this session (see *Final
verification*), but **not yet exercised against a live Cloud Run backend**,
since that requires an actual deployment.

### Optional: custom domain

Once the `.pages.dev` URL works, Cloudflare Pages → Custom domains lets you
attach a domain you own, free (Cloudflare doesn't charge for this; you pay
your registrar for the domain itself, if you don't already have one). Update
`CORS_ALLOW_ORIGINS` on Cloud Run to the new domain when you do. This step is
entirely optional — nothing in this deployment requires it.

## Environment variables

`.env.example` at the repo root lists every variable with local-dev defaults.
This table is the same variables, organized for a **production** deployment.

### REQUIRED (deployment fails or is insecure without these)

| Variable | Purpose |
|---|---|
| `APP_PROFILE=prod` | enables prod-only validation (strong `JWT_SECRET`, `SESSION_COOKIE_SECURE=true`, rejects fake providers) |
| `DATABASE_URL` | Neon connection string, `?sslmode=require` included |
| `REDIS_URL` | Upstash `rediss://` connection string |
| `QDRANT_URL`, `QDRANT_API_KEY` | Qdrant Cloud cluster |
| `LLM_PROVIDER=openai`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` | Gemini, via the OpenAI-compatible provider |
| `JWT_SECRET` | ≥32 random chars — `openssl rand -hex 32` |
| `SESSION_COOKIE_SECURE=true` | required in prod; refresh cookie is dropped by browsers over HTTP otherwise |
| `STORAGE_BACKEND=s3`, `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Cloudflare R2 |
| `CORS_ALLOW_ORIGINS` | exact Cloudflare Pages URL |
| `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` | first admin account (set once for `rag bootstrap`; the app has no other way to create the first user when `ALLOW_OPEN_REGISTRATION=false`) |

### OPTIONAL (safe defaults exist)

| Variable | Default | Notes |
|---|---|---|
| `EMBEDDING_PROVIDER` | `fastembed` | CPU ONNX, no key needed |
| `RERANKER` | `fastembed_cross_encoder` | CPU ONNX, no key needed |
| `S3_REGION` | `us-east-1` | set to `auto` for R2 |
| `ALLOW_OPEN_REGISTRATION` | `false` | leave `false` for a demo unless you want public sign-up |
| `RATE_LIMIT_PER_MIN`, `RATE_LIMIT_BURST` | `120`, `40` | lower these for a public demo on a shared free LLM budget |
| `SESSION_COOKIE_SAMESITE` | `lax` | fine for the same-origin-via-proxy setup here |
| `SEED_ON_BOOTSTRAP` | `false` | set `true` once to pre-load the demo corpus |
| `PROMPT_VERSION`, retrieval tuning (`RETRIEVAL__*`) | see `.env.example` | unchanged from local defaults |

### DEPLOYMENT ONLY (new in this document; not used in local docker-compose)

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | set by Cloud Run at runtime, not by you — `app/server.py` reads it |
| `WORKER_MODE` | `queue` | set `inline` for this free deployment — see `DEPLOYMENT_ARCHITECTURE.md` |
| `DATABASE_URL` | unset | overrides discrete `POSTGRES_*` fields when set |
| `REDIS_URL` | unset | overrides discrete `REDIS_*` fields when set |

### LOCAL ONLY (docker-compose; do not set these in Cloud Run)

`POSTGRES_HOST/PORT/USER/PASSWORD/DB`, `REDIS_HOST/PORT/PASSWORD/DB`,
`STORAGE_LOCAL_PATH`, `BIND_HOST=127.0.0.1` — all superseded by
`DATABASE_URL`/`REDIS_URL`/`STORAGE_BACKEND=s3` in this deployment, and
`BIND_HOST` doesn't apply to a container that must bind `0.0.0.0` for Cloud
Run to reach it (`app/server.py` already always binds `0.0.0.0`; `BIND_HOST`
only affects `AUTH_MODE=single_user`'s loopback check, which doesn't apply
here since this deployment uses `AUTH_MODE=multi_user`).

Never commit real values for any of the above — see *Git hygiene* below.

## CI/CD

`.github/workflows/deploy.yml` (added alongside this document) is a
`workflow_dispatch`-only workflow — it does **not** run on every push, so
merging to `main` cannot trigger unexpected Cloud Run/Cloud Build usage. You
trigger it manually (Actions tab → "deploy" → Run workflow) once you've set
up the GitHub repo secrets/variables it needs. It:

1. Runs the same lint/type-check/test/build steps as `ci.yml`.
2. On success, authenticates to Google Cloud via **Workload Identity
   Federation** (OIDC) — no long-lived service-account JSON key is stored in
   GitHub. Follow [Google's guide](https://github.com/google-github-actions/auth#setting-up-workload-identity-federation)
   to create the pool/provider once; the workflow file documents the exact
   repo secrets it expects (`GCP_WORKLOAD_IDENTITY_PROVIDER`,
   `GCP_SERVICE_ACCOUNT`, `GCP_PROJECT_ID`).
3. Builds and pushes the Cloud Run image, then runs `gcloud run deploy`.

This workflow has not been run (no GCP project or repo secrets are
configured for it in this session) — it's prepared and ready to enable, not
verified end-to-end.

## Production smoke test

Run manually against the real deployed URL, with real providers (no
`LLM_PROVIDER=fake`) — this has **not** been executed, since no public URL
exists yet:

1. Open `https://<your-project>.pages.dev`.
2. Register a new user (or log in, if `ALLOW_OPEN_REGISTRATION=false` and you
   use the bootstrap admin).
3. Log in.
4. Create a knowledge base.
5. Upload a document (e.g. `seed/handbook.md` or any PDF/DOCX/TXT/MD).
6. Wait for ingestion. With `WORKER_MODE=inline`, the upload request itself
   blocks until this finishes — the UI should show the document as `ready`
   once the request completes (or shortly after, if the UI polls status
   separately).
7. Confirm the document's status is `READY` (not `failed`/`processing`).
8. Ask a question whose answer is in the document.
9. Confirm the answer is grounded (references the uploaded content, not a
   generic LLM answer).
10. Confirm at least one `[[n]]` citation is present and non-weak.
11. Ask an unrelated question (not answerable from the KB) and confirm the
    app abstains rather than hallucinating an answer.
12. Log out, confirm the session actually ends (a subsequent authenticated
    request fails without logging back in).
13. Confirm refresh-token behavior: reload the page after login (before
    logging out) and confirm the session survives via the `HttpOnly` cookie
    without re-entering credentials.
14. Register a second user, confirm they **cannot** see or query the first
    user's knowledge base (expect `404`, per `app/api/deps.py`'s
    membership-boundary design — a non-member gets `404`, not `403`).

Record actual results (pass/fail per step, and any latency/behavior
observed) once you run this — do not treat this checklist as a substitute
for having actually run it.

## Costs and free-tier limits — read before relying on this

- **This document does not guarantee $0.** Cloud Run, Neon, Qdrant Cloud,
  Upstash, and Cloudflare all publish free-tier quotas that this deployment
  is designed to fit under for light demo traffic, but:
  - Free-tier limits change over time and vary by provider policy.
  - `WORKER_MODE=inline` means ingestion CPU time is billed as part of the
    request that triggered it — a burst of large-document uploads could use
    meaningfully more Cloud Run compute time than a light "ask a few
    questions" demo load.
  - Scale-to-zero (`--min-instances=0`) is what keeps Cloud Run free-tier
    friendly; setting `--min-instances=1` for lower latency removes the
    scale-to-zero cost benefit and will likely incur real charges.
- **Set a billing alert** on the GCP project before directing real traffic at
  this deployment (Billing → Budgets & alerts). This is on you to configure;
  nothing in this repository does it for you.
- **Cold starts are real and unmeasured here.** No latency numbers in this
  document are measured — they have not been benchmarked against a live
  deployment. Expect a multi-second delay on the first request after a period
  of no traffic (container start + model load from the pre-baked image
  cache + first DB/Redis/Qdrant connections).
- **No uptime/SLA claim.** This is a production-oriented open-source demo on
  free infrastructure, not a guaranteed always-on service.

## Git hygiene

`.env`, and anything containing a real key/secret/password, must never be
committed. Verified for this repository (checked in this session):

- `.env` is listed in `.gitignore` (`.env`, `.env.*`, with `!.env.example`
  excepted) and is not tracked (`git ls-files` confirms).
- No R2/Neon/Upstash/Qdrant/Gemini credential strings exist anywhere in this
  repository's tracked files or git history (checked with a pattern scan
  across `git log --all` and the working tree; see the branch's own commit
  history for the equivalent check already run before this deployment work).
- Before committing changes from this deployment work, run the same checks
  again: `git status` (nothing unexpected staged), and a secret-pattern scan
  of the diff (e.g. `git diff | grep -iE 'api[_-]?key|secret|password|token'`
  and inspect every hit by hand — a keyword match alone is not proof of a
  real secret, and its absence is not proof there isn't one either).
