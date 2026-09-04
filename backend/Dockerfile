# syntax=docker/dockerfile:1
# Backend image — shared by the `api`, `worker` and `bootstrap` services
# (docs/ARCHITECTURE.md §27). Multi-stage, non-root, no PyTorch (ADR 0004).

FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, for layer caching.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Then the project itself.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

RUN groupadd --system app && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini pyproject.toml ./
RUN mkdir -p /data/uploads /data/models && chown -R app:app /data
ENV FASTEMBED_CACHE_PATH=/data/models \
    HF_HOME=/data/models

USER app
EXPOSE 8000

# Fail-fast on invalid configuration, then start uvicorn (docs/ARCHITECTURE.md §2).
CMD ["python", "-m", "app.server"]
