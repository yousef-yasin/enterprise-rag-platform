# enterprise-rag-platform — developer commands (docs/ARCHITECTURE.md §35).
# Run from a POSIX shell (on Windows: WSL2 or Git Bash — see ARCHITECTURE.md §2).
# Run `make help` for the full target list.

.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

UV      ?= uv
COMPOSE ?= docker compose
BACKEND := backend

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── setup / dev ────────────────────────────────────────────────────────────────
.PHONY: setup
setup: ## Install the toolchain and backend dependencies (creates backend/.venv)
	@command -v $(UV) >/dev/null 2>&1 || { \
		echo "uv not found — install: https://docs.astral.sh/uv/getting-started/installation/"; \
		exit 1; }
	cd $(BACKEND) && $(UV) sync
	@echo
	@echo "Setup complete."
	@echo "  A .env file is optional — docker compose ships safe local defaults."
	@echo "  Path A (hosted LLM): export LLM_API_KEY=... then 'make dev'"
	@echo "  Path B (local):      'make dev-local'   (Ollama; heavier — see ARCHITECTURE.md §2)"
	@echo "  Copy .env.example to .env to customise anything."

.PHONY: dev
dev: ## Start the full stack with hot reload (compose + override)
	$(COMPOSE) up --build

.PHONY: dev-local
dev-local: ## Start the stack with the local Ollama profile (Path B)
	$(COMPOSE) --profile local up --build

.PHONY: down
down: ## Stop the stack (keep volumes)
	$(COMPOSE) down --remove-orphans

.PHONY: reset
reset: ## Stop the stack and DELETE all volumes (Postgres / Qdrant / Redis / models)
	$(COMPOSE) down -v --remove-orphans
	-$(COMPOSE) -f compose.test.yml down -v --remove-orphans

# ── quality gate ──────────────────────────────────────────────────────────────
.PHONY: lint
lint: ## ruff lint + format check
	cd $(BACKEND) && $(UV) run ruff check . && $(UV) run ruff format --check .

.PHONY: format
format: ## ruff autofix + format
	cd $(BACKEND) && $(UV) run ruff check --fix . && $(UV) run ruff format .

.PHONY: typecheck
typecheck: ## mypy (strict)
	cd $(BACKEND) && $(UV) run mypy

.PHONY: test
test: ## Run unit tests
	cd $(BACKEND) && $(UV) run pytest tests/unit

.PHONY: test-integration
test-integration: ## Start ephemeral infra and run integration tests
	$(COMPOSE) -f compose.test.yml up -d --wait
	cd $(BACKEND) && ( \
		RAG_INTEGRATION=1 APP_PROFILE=ci LLM_PROVIDER=fake EMBEDDING_PROVIDER=fake \
		POSTGRES_HOST=127.0.0.1 QDRANT_URL=http://127.0.0.1:6333 REDIS_HOST=127.0.0.1 \
		$(UV) run pytest tests/integration -m integration; \
		status=$$?; cd ..; $(COMPOSE) -f compose.test.yml down -v; exit $$status )

.PHONY: compose-config
compose-config: ## Validate the compose configuration (no .env required)
	$(COMPOSE) config --quiet && echo "compose config OK"

.PHONY: check
check: lint typecheck test compose-config ## Run the full local quality gate

.PHONY: frontend-check
frontend-check: ## Frontend lint + typecheck + unit tests + build
	cd frontend && npm ci && npm run lint && npm run typecheck && npm run test && npm run build

# ── evaluation ────────────────────────────────────────────────────────────────
.PHONY: eval
eval: ## Run the smoke evaluation split end-to-end (fake providers)
	$(COMPOSE) -f compose.test.yml up -d --wait
	cd $(BACKEND) && ( \
		RAG_INTEGRATION=1 APP_PROFILE=ci LLM_PROVIDER=fake EMBEDDING_PROVIDER=fake RERANKER=none \
		POSTGRES_HOST=127.0.0.1 QDRANT_URL=http://127.0.0.1:6333 REDIS_HOST=127.0.0.1 \
		$(UV) run alembic upgrade head && \
		RAG_INTEGRATION=1 APP_PROFILE=ci LLM_PROVIDER=fake EMBEDDING_PROVIDER=fake RERANKER=none \
		POSTGRES_HOST=127.0.0.1 QDRANT_URL=http://127.0.0.1:6333 REDIS_HOST=127.0.0.1 \
		$(UV) run python ../scripts/run_eval.py --dataset handbook --split smoke; \
		status=$$?; cd ..; $(COMPOSE) -f compose.test.yml down -v; exit $$status )

.PHONY: e2e
e2e: ## Bring up the full stack (fake providers) and run the golden flow
	APP_PROFILE=ci LLM_PROVIDER=fake EMBEDDING_PROVIDER=fake RERANKER=none \
		ALLOW_OPEN_REGISTRATION=true $(COMPOSE) up -d --build --wait
	bash scripts/e2e_smoke.sh; status=$$?; $(COMPOSE) down -v; exit $$status
