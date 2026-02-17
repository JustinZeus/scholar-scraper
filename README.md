# scholarr

<div align="center">

API-first, self-hosted scholar tracking in the spirit of the `*arr` ecosystem.

[![CI](https://img.shields.io/github/actions/workflow/status/justinzeus/scholarr/ci.yml?style=for-the-badge)](https://github.com/justinzeus/scholarr/actions/workflows/ci.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/justinzeus/scholarr?style=for-the-badge&logo=docker)](https://hub.docker.com/r/justinzeus/scholarr)
[![Docker Image](https://img.shields.io/badge/docker-justinzeus%2Fscholarr-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://hub.docker.com/r/justinzeus/scholarr)

</div>

## What This Includes

- Multi-user accounts with admin-managed lifecycle
- Cookie session auth with CSRF enforcement
- Scholar CRUD + name-search discovery + profile image management
- Per-user ingestion settings and scheduler
- Manual runs with idempotency behavior
- Run history and continuation queue diagnostics/actions
- Publications workflow (`new` / `all`, mark-selected-read, mark-all-read)
- Vue 3 + Vite frontend served from the same container image as the API

## Docker Image

- Image: `justinzeus/scholarr`
- Published by GitHub Actions on every push to `main`
- Architectures: `linux/amd64`, `linux/arm64`
- Tags:
  - `latest`
  - `sha-<short_commit>`

## Quick Deploy (Copy Compose + Fill Env)

1. Copy `docker-compose.yml` and `.env.example` into your deployment directory.
2. Create `.env` from `.env.example`.
3. Set at minimum:
   - `SESSION_SECRET_KEY`
   - `POSTGRES_PASSWORD`
4. Pull and start:

```bash
docker compose pull
docker compose up -d
```

5. Open:

- App + API: `http://localhost:8000`
- Health check: `http://localhost:8000/healthz`

The SPA and API are same-origin by default in this deployment model.

## Required Environment Variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `SESSION_SECRET_KEY` | Yes | Session signing key. Use a long random value. |
| `POSTGRES_PASSWORD` | Yes | Database password for the bundled Postgres service. |

Optional startup bootstrap:

| Variable | Default | Purpose |
| --- | --- | --- |
| `BOOTSTRAP_ADMIN_ON_START` | `0` | Auto-create admin on app start. |
| `BOOTSTRAP_ADMIN_EMAIL` | empty | Admin email for bootstrap. |
| `BOOTSTRAP_ADMIN_PASSWORD` | empty | Admin password for bootstrap. |
| `BOOTSTRAP_ADMIN_FORCE_PASSWORD` | `0` | Force-reset bootstrap admin password if exists. |

## Ports

| Port | Service | Description |
| --- | --- | --- |
| `8000` | `app` | scholarr API + frontend |

## Volumes

| Volume | Container Path | Purpose |
| --- | --- | --- |
| `postgres_data` | `/var/lib/postgresql/data` | Postgres persistence |
| `scholar_uploads` | `/var/lib/scholarr/uploads` | Scholar image upload persistence |

## Upgrade

```bash
docker compose pull
docker compose up -d
```

## Development Workflow

Default `docker-compose.yml` is deployment-oriented (prebuilt image).

For local development with source mounts + Vite dev server:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Then open:

- API: `http://localhost:8000`
- Frontend dev server: `http://localhost:5173`

## Test and Quality Commands

Backend:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app uv run pytest tests/unit
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app uv run pytest -m integration
```

Frontend:

```bash
cd frontend
npm install
npm run typecheck
npm run test:run
npm run build
```

Contract drift check:

```bash
python3 scripts/check_frontend_api_contract.py
```

## API Base

- Base path: `/api/v1`
- Success envelope:
  - `{"data": ..., "meta": {"request_id": "..."}}`
- Error envelope:
  - `{"error": {"code": "...", "message": "...", "details": ...}, "meta": {"request_id": "..."}}`

## Logging

Important envs:

- `LOG_LEVEL`
- `LOG_FORMAT` (`console` or `json`)
- `LOG_REQUESTS`
- `LOG_UVICORN_ACCESS`
- `LOG_REQUEST_SKIP_PATHS`
- `LOG_REDACT_FIELDS`
