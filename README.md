# scholarr

API-first, self-hosted scholar tracking backend in the spirit of the `*arr` ecosystem.

The legacy server-rendered UI has been removed. This repository now focuses on core ingestion, scheduling, and multi-user API functionality.

## Current Scope

- Multi-user accounts with admin-managed user lifecycle
- Same-origin cookie sessions with CSRF enforcement
- API auth flows (login, logout, me, password change)
- Admin user management API
- Scholar CRUD per user
- Per-user ingestion settings
- Manual runs with idempotency support
- Run history, run detail diagnostics, and continuation queue actions
- Publication listing (`new` / `all`) and mark-all-read
- Ingestion scheduler + continuation queue retries
- Structured logging with request IDs + redaction
- PostgreSQL + Alembic migrations
- Container-first development workflow with `uv`

## Functionality Tracking

Planned and supported backend functionality is tracked in:

- `AGENTS.MD`

## API Base

- Base path: `/api/v1`
- Success envelope:
  - `{"data": ..., "meta": {"request_id": "..."}}`
- Error envelope:
  - `{"error": {"code": "...", "message": "...", "details": ...}, "meta": {"request_id": "..."}}`

## Auth & Session Model

- Session transport: same-origin cookie session (`HttpOnly`, `SameSite=Lax`)
- CSRF:
  - Required for unsafe methods (`POST`, `PUT`, `PATCH`, `DELETE`) via `X-CSRF-Token`
  - Bootstrap token via `GET /api/v1/auth/csrf`

## API Surface

- Auth:
  - `GET /api/v1/auth/csrf`
  - `POST /api/v1/auth/login`
  - `GET /api/v1/auth/me`
  - `POST /api/v1/auth/change-password`
  - `POST /api/v1/auth/logout`
- Admin users:
  - `GET /api/v1/admin/users`
  - `POST /api/v1/admin/users`
  - `PATCH /api/v1/admin/users/{id}/active`
  - `POST /api/v1/admin/users/{id}/reset-password`
- Scholars:
  - `GET /api/v1/scholars`
  - `POST /api/v1/scholars`
  - `PATCH /api/v1/scholars/{id}/toggle`
  - `DELETE /api/v1/scholars/{id}`
- Settings:
  - `GET /api/v1/settings`
  - `PUT /api/v1/settings`
- Runs:
  - `GET /api/v1/runs`
  - `GET /api/v1/runs/{id}`
  - `POST /api/v1/runs/manual` (`Idempotency-Key` supported)
  - `GET /api/v1/runs/queue/items`
  - `POST /api/v1/runs/queue/{id}/retry`
  - `POST /api/v1/runs/queue/{id}/drop`
  - `DELETE /api/v1/runs/queue/{id}`
- Publications:
  - `GET /api/v1/publications`
  - `POST /api/v1/publications/mark-all-read`
- Ops:
  - `GET /healthz`

## Quick Start

1. Copy environment defaults:

```bash
cp .env.example .env
```

2. Optional bootstrap admin on startup:

```bash
export BOOTSTRAP_ADMIN_ON_START=1
export BOOTSTRAP_ADMIN_EMAIL=admin@example.com
export BOOTSTRAP_ADMIN_PASSWORD=change-me-now
```

3. Start stack:

```bash
docker compose up --build
```

4. Health check:

```text
http://localhost:8000/healthz
```

## Admin Bootstrap (Manual)

```bash
docker compose run --rm app uv run python scripts/bootstrap_admin.py \
  --email admin@example.com \
  --password change-me-now \
  --force-password
```

## Test Workflow

- Unit tests:

```bash
docker compose run --rm app uv run pytest tests/unit
```

- Integration tests:

```bash
docker compose run --rm app uv run pytest -m integration
```

- Smoke checks:

```bash
./scripts/smoke_compose.sh
```

## Logging

Configurable env vars:

- `LOG_LEVEL` (default `INFO`)
- `LOG_FORMAT` (`console` or `json`, default `console`)
- `LOG_REQUESTS` (`1`/`0`, default `1`)
- `LOG_UVICORN_ACCESS` (`1`/`0`, default `0`)
- `LOG_REQUEST_SKIP_PATHS` (default `/healthz`)
- `LOG_REDACT_FIELDS` (additional redact keys)

## Project Layout

```text
app/         FastAPI app (API routers, auth, services, db, middleware)
alembic/     Migration environment and versions
scripts/     Entrypoint, db wait/bootstrap, smoke automation
tests/       Unit, integration, and smoke suites
planning/    Scope and implementation planning notes
```
