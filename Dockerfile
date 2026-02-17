FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.6.5 /uv /uvx /bin/

COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY scripts ./scripts

RUN uv sync --frozen --extra dev

FROM base AS dev
ENTRYPOINT ["/bin/sh", "/app/scripts/entrypoint.sh"]

FROM python:3.12-slim AS prod

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    APP_RELOAD=0 \
    UVICORN_WORKERS=1 \
    FRONTEND_ENABLED=1 \
    FRONTEND_DIST_DIR=/app/frontend/dist

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.6.5 /uv /uvx /bin/

COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

RUN uv sync --frozen

COPY scripts ./scripts
COPY --from=frontend-builder /frontend/dist /app/frontend/dist
ENTRYPOINT ["/bin/sh", "/app/scripts/entrypoint.sh"]
