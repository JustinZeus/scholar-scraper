# scholarr

<div align="center">

Self-hosted scholar tracking with a single app image (API + frontend).

[![CI](https://img.shields.io/github/actions/workflow/status/justinzeus/scholarr/ci.yml?style=for-the-badge)](https://github.com/justinzeus/scholarr/actions/workflows/ci.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/justinzeus/scholarr?style=for-the-badge&logo=docker)](https://hub.docker.com/r/justinzeus/scholarr)
[![Docker Image](https://img.shields.io/badge/docker-justinzeus%2Fscholarr-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://hub.docker.com/r/justinzeus/scholarr)

</div>

## Quick Start

1. Copy env template:

```bash
cp .env.example .env
```

2. Set required values in `.env`:
- `POSTGRES_PASSWORD`
- `SESSION_SECRET_KEY`

3. Choose a deploy method below.

## Deploy Method A: Prebuilt Image (Recommended)

Use this for normal self-hosted deployment.

```bash
docker compose pull
docker compose up -d
```

Open:
- App/API: `http://localhost:8000`
- Health: `http://localhost:8000/healthz`

Upgrade:

```bash
docker compose pull
docker compose up -d
```

## Deploy Method B: Local Source Build + Dev Frontend

Use this for development on this repository.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Open:
- API (FastAPI): `http://localhost:8000`
- Frontend dev server (Vite): `http://localhost:5173`

Stop:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

## Essential Files

- `docker-compose.yml`: deployment compose (prebuilt image).
- `docker-compose.dev.yml`: dev override (source mounts + Vite dev server).
- `.env.example`: full env variable template.
- `Dockerfile`: multi-stage build (frontend + backend runtime).
- `README.md`: deployment and operations reference.
- `CONTRIBUTING.md`: contribution policy and merge checklist.
- `docs/ops/scrape_safety_runbook.md`: scrape cooldown and blocked-IP operations guide.
- `scripts/check_no_generated_artifacts.sh`: tracked-artifact guard used by CI.

## Data Model Notes

- Scholar tracking is user-scoped: each account can track the same Scholar ID independently.
- Publications are shared/global records deduplicated by Scholar cluster ID and normalized fingerprint.
- Per-account visibility and read state is stored on scholar-publication links, not on the global publication row.

## Name Search Status

- Scholar name search is intentionally WIP in the UI.
- Current Google Scholar behavior often redirects name-search traffic to login/challenge flows, so production onboarding should use direct Scholar ID/profile URL adds.

## Environment Variables (Complete Reference)

Notes:
- Boolean envs accept: `1/0`, `true/false`, `yes/no`, `on/off`.
- Values shown are deployment defaults from `.env.example` and `docker-compose.yml`.
- Some internal app fallbacks may differ for local test/dev safety when env vars are omitted.
- `deploy` means used in regular deployment.
- `dev` means used in local dev workflow.

### Core Compose and Database

| Variable | Default | Options | Scope | Description |
| --- | --- | --- | --- | --- |
| `POSTGRES_DB` | `scholar` | any valid DB name | deploy, dev | PostgreSQL database name. |
| `POSTGRES_USER` | `scholar` | any valid DB user | deploy, dev | PostgreSQL user. |
| `POSTGRES_PASSWORD` | `change-me` | strong password | deploy, dev | PostgreSQL password. Required. |
| `DATABASE_URL` | `postgresql+asyncpg://scholar:scholar@db:5432/scholar` | valid SQLAlchemy asyncpg URL | deploy, dev, test | App database connection URL. |
| `TEST_DATABASE_URL` | empty | valid SQLAlchemy asyncpg URL | test | Optional explicit integration test DB URL. |
| `SCHOLARR_IMAGE` | `justinzeus/scholarr:latest` | any image ref | deploy | App image tag used by deployment compose. |

### App Runtime and Networking

| Variable | Default | Options | Scope | Description |
| --- | --- | --- | --- | --- |
| `APP_NAME` | `scholarr` | any string | deploy, dev | FastAPI app name/title. |
| `APP_HOST` | `0.0.0.0` | bind host | deploy, dev | Uvicorn bind host inside container. |
| `APP_PORT` | `8000` | integer | deploy, dev | Uvicorn bind port inside container. |
| `APP_HOST_PORT` | `8000` | integer | deploy, dev | Host port mapped to app container port 8000. |
| `APP_RELOAD` | `0` | boolean | deploy, dev | Enable uvicorn reload mode. Recommended `0` in deploy, `1` in dev. |
| `MIGRATE_ON_START` | `1` | boolean | deploy, dev | Run Alembic migrations during app startup. |
| `FRONTEND_ENABLED` | `1` | boolean | deploy, dev | Serve bundled frontend assets from FastAPI. |
| `FRONTEND_DIST_DIR` | `/app/frontend/dist` | absolute path | deploy, dev | Path to built frontend assets inside app container. |

### Dev Frontend Overrides

| Variable | Default | Options | Scope | Description |
| --- | --- | --- | --- | --- |
| `FRONTEND_HOST_PORT` | `5173` | integer | dev | Host port mapped to Vite dev server. |
| `CHOKIDAR_USEPOLLING` | `1` | boolean | dev | File watching mode for containerized Vite. |
| `VITE_DEV_API_PROXY_TARGET` | `http://app:8000` | URL | dev | Vite proxy target for `/api` and `/healthz`. |

### Auth and Session Security

| Variable | Default | Options | Scope | Description |
| --- | --- | --- | --- | --- |
| `SESSION_SECRET_KEY` | `replace-with-a-long-random-secret-at-least-32-characters` | long random string | deploy, dev | Session signing secret. Required in deploy. |
| `SESSION_COOKIE_SECURE` | `1` | boolean | deploy, dev | Mark session cookie as HTTPS-only. Set `1` behind HTTPS. |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | `5` | integer >= 1 | deploy, dev | Login attempts allowed per window. |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `60` | integer >= 1 | deploy, dev | Login rate limit window in seconds. |

### HTTP Security Headers and CSP

| Variable | Default | Options | Scope | Description |
| --- | --- | --- | --- | --- |
| `SECURITY_HEADERS_ENABLED` | `1` | boolean | deploy, dev | Global switch for response security headers middleware. |
| `SECURITY_X_CONTENT_TYPE_OPTIONS` | `nosniff` | header value | deploy, dev | `X-Content-Type-Options` response header value. |
| `SECURITY_X_FRAME_OPTIONS` | `DENY` | header value | deploy, dev | `X-Frame-Options` response header value. |
| `SECURITY_REFERRER_POLICY` | `strict-origin-when-cross-origin` | header value | deploy, dev | `Referrer-Policy` response header value. |
| `SECURITY_PERMISSIONS_POLICY` | `accelerometer=(), autoplay=(), camera=(), display-capture=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()` | permissions policy string | deploy, dev | `Permissions-Policy` response header value. |
| `SECURITY_CROSS_ORIGIN_OPENER_POLICY` | `same-origin` | header value | deploy, dev | `Cross-Origin-Opener-Policy` response header value. |
| `SECURITY_CROSS_ORIGIN_RESOURCE_POLICY` | `same-origin` | header value | deploy, dev | `Cross-Origin-Resource-Policy` response header value. |
| `SECURITY_CSP_ENABLED` | `1` | boolean | deploy, dev | Enable Content Security Policy headers. |
| `SECURITY_CSP_POLICY` | strict SPA/API default | CSP policy string | deploy, dev | CSP applied to app/API routes (excluding docs paths). |
| `SECURITY_CSP_DOCS_POLICY` | relaxed docs default | CSP policy string | deploy, dev | CSP override for `/docs` and `/redoc` to keep Swagger/ReDoc usable. |
| `SECURITY_CSP_REPORT_ONLY` | `0` | boolean | deploy, dev | Emit CSP in report-only mode instead of enforcement mode. |
| `SECURITY_STRICT_TRANSPORT_SECURITY_ENABLED` | `0` | boolean | deploy, dev | Enable `Strict-Transport-Security` header. |
| `SECURITY_STRICT_TRANSPORT_SECURITY_MAX_AGE` | `31536000` | integer >= 0 | deploy, dev | `max-age` for HSTS header. |
| `SECURITY_STRICT_TRANSPORT_SECURITY_INCLUDE_SUBDOMAINS` | `1` | boolean | deploy, dev | Add `includeSubDomains` directive to HSTS header. |
| `SECURITY_STRICT_TRANSPORT_SECURITY_PRELOAD` | `0` | boolean | deploy, dev | Add `preload` directive to HSTS header. |

### Logging

| Variable | Default | Options | Scope | Description |
| --- | --- | --- | --- | --- |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | deploy, dev | Application log level. |
| `LOG_FORMAT` | `console` | `console`, `json` | deploy, dev | Log output format. |
| `LOG_REQUESTS` | `1` | boolean | deploy, dev | Enable request start/completion logs. |
| `LOG_UVICORN_ACCESS` | `0` | boolean | deploy, dev | Enable uvicorn access logs. |
| `LOG_REQUEST_SKIP_PATHS` | `/healthz` | comma-separated path prefixes | deploy, dev | Request log skip list. |
| `LOG_REDACT_FIELDS` | empty | comma-separated keys | deploy, dev | Extra fields to redact in structured logs. |

### Scheduler and Ingestion

| Variable | Default | Options | Scope | Description |
| --- | --- | --- | --- | --- |
| `SCHEDULER_ENABLED` | `1` | boolean | deploy, dev | Enable background scheduler loop. |
| `SCHEDULER_TICK_SECONDS` | `60` | integer >= 1 | deploy, dev | Scheduler interval in seconds. |
| `INGESTION_AUTOMATION_ALLOWED` | `1` | boolean | deploy, dev | Global safety switch for scheduled/automatic checks. When disabled, auto-run settings are forced off. |
| `INGESTION_MANUAL_RUN_ALLOWED` | `1` | boolean | deploy, dev | Global safety switch for manual checks from API/UI. |
| `INGESTION_MIN_RUN_INTERVAL_MINUTES` | `15` | integer >= 15 | deploy, dev | Server-enforced minimum for user-configured automatic check interval. |
| `INGESTION_MIN_REQUEST_DELAY_SECONDS` | `2` | integer >= 2 | deploy, dev | Server-enforced minimum delay between scholar requests. |
| `SCHEDULER_QUEUE_BATCH_SIZE` | `10` | integer >= 1 | deploy, dev | Queue items processed per scheduler tick. |
| `INGESTION_NETWORK_ERROR_RETRIES` | `1` | integer >= 0 | deploy, dev | Retries for transient ingestion network errors. |
| `INGESTION_RETRY_BACKOFF_SECONDS` | `1.0` | float >= 0 | deploy, dev | Backoff delay for retry attempts. |
| `INGESTION_MAX_PAGES_PER_SCHOLAR` | `30` | integer >= 1 | deploy, dev | Upper bound of pages fetched per scholar run. |
| `INGESTION_PAGE_SIZE` | `100` | integer >= 1 | deploy, dev | Requested Scholar page size. |
| `INGESTION_ALERT_BLOCKED_FAILURE_THRESHOLD` | `1` | integer >= 1 | deploy, dev | Trigger blocked/captcha scrape alert flag when this many blocked failures occur in a run. |
| `INGESTION_ALERT_NETWORK_FAILURE_THRESHOLD` | `2` | integer >= 1 | deploy, dev | Trigger network scrape alert flag when this many network failures occur in a run. |
| `INGESTION_ALERT_RETRY_SCHEDULED_THRESHOLD` | `3` | integer >= 1 | deploy, dev | Trigger retry alert flag when scheduled retry count reaches this threshold in a run. |
| `INGESTION_SAFETY_COOLDOWN_BLOCKED_SECONDS` | `1800` | integer >= 60 | deploy, dev | Cooldown duration applied when blocked-failure threshold is exceeded. |
| `INGESTION_SAFETY_COOLDOWN_NETWORK_SECONDS` | `900` | integer >= 60 | deploy, dev | Cooldown duration applied when network-failure threshold is exceeded. |
| `INGESTION_CONTINUATION_QUEUE_ENABLED` | `1` | boolean | deploy, dev | Enable continuation queue for long runs. |
| `INGESTION_CONTINUATION_BASE_DELAY_SECONDS` | `120` | integer >= 0 | deploy, dev | Initial delay before retrying continuation queue items. |
| `INGESTION_CONTINUATION_MAX_DELAY_SECONDS` | `3600` | integer >= 0 | deploy, dev | Maximum continuation retry delay. |
| `INGESTION_CONTINUATION_MAX_ATTEMPTS` | `6` | integer >= 1 | deploy, dev | Max failed continuation attempts before dropping item. |

### Scholar Images and Name Search Safety

| Variable | Default | Options | Scope | Description |
| --- | --- | --- | --- | --- |
| `SCHOLAR_IMAGE_UPLOAD_DIR` | `/var/lib/scholarr/uploads` | writable absolute path | deploy, dev | Storage path for uploaded scholar images in compose deployments. App fallback without env is `/tmp/scholarr_uploads/scholar_images`. |
| `SCHOLAR_IMAGE_UPLOAD_MAX_BYTES` | `2000000` | integer >= 1 | deploy, dev | Max uploaded image size in bytes. |
| `SCHOLAR_NAME_SEARCH_ENABLED` | `1` | boolean | deploy, dev | Enable name-search helper endpoint. |
| `SCHOLAR_NAME_SEARCH_CACHE_TTL_SECONDS` | `21600` | integer >= 1 | deploy, dev | Cache TTL for successful name-search responses. |
| `SCHOLAR_NAME_SEARCH_BLOCKED_CACHE_TTL_SECONDS` | `300` | integer >= 1 | deploy, dev | Cache TTL for blocked/captcha responses. |
| `SCHOLAR_NAME_SEARCH_CACHE_MAX_ENTRIES` | `512` | integer >= 1 | deploy, dev | Max cached search entries. |
| `SCHOLAR_NAME_SEARCH_MIN_INTERVAL_SECONDS` | `8.0` | float >= 0 | deploy, dev | Minimum interval between live name-search requests. |
| `SCHOLAR_NAME_SEARCH_INTERVAL_JITTER_SECONDS` | `2.0` | float >= 0 | deploy, dev | Added jitter to reduce request burst patterns. |
| `SCHOLAR_NAME_SEARCH_COOLDOWN_BLOCK_THRESHOLD` | `1` | integer >= 1 | deploy, dev | Consecutive blocked responses before cooldown starts. |
| `SCHOLAR_NAME_SEARCH_COOLDOWN_SECONDS` | `1800` | integer >= 1 | deploy, dev | Cooldown duration after repeated blocked responses. |
| `SCHOLAR_NAME_SEARCH_ALERT_RETRY_COUNT_THRESHOLD` | `2` | integer >= 1 | deploy, dev | Emit retry-threshold observability warning when name-search retry count reaches this value. |
| `SCHOLAR_NAME_SEARCH_ALERT_COOLDOWN_REJECTIONS_THRESHOLD` | `3` | integer >= 1 | deploy, dev | Emit cooldown-threshold observability alert after this many requests are rejected during active cooldown. |

### Scrape Safety Operations

- Structured safety events are emitted for:
  - policy/manual run blocks,
  - cooldown entered/cleared transitions,
  - blocked/network/retry threshold trips,
  - scheduler cooldown skips/deferments.
- Use `LOG_FORMAT=json` and ship logs to your preferred collector for alerting.
- Runbook: `docs/ops/scrape_safety_runbook.md`.

### Startup Bootstrap and DB Wait

| Variable | Default | Options | Scope | Description |
| --- | --- | --- | --- | --- |
| `BOOTSTRAP_ADMIN_ON_START` | `0` | boolean | deploy, dev | Auto-create admin at startup. |
| `BOOTSTRAP_ADMIN_EMAIL` | empty | valid email | deploy, dev | Bootstrap admin email. |
| `BOOTSTRAP_ADMIN_PASSWORD` | empty | strong password | deploy, dev | Bootstrap admin password. |
| `BOOTSTRAP_ADMIN_FORCE_PASSWORD` | `0` | boolean | deploy, dev | Force-reset bootstrap admin password if user already exists. |
| `DB_WAIT_TIMEOUT_SECONDS` | `60` | integer >= 1 | deploy, dev | Max seconds to wait for DB readiness at startup. |
| `DB_WAIT_INTERVAL_SECONDS` | `2` | integer >= 1 | deploy, dev | Interval between DB readiness checks. |

## Quality and Test Commands

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

Contract drift:

```bash
python3 scripts/check_frontend_api_contract.py
```

Repository hygiene:

```bash
./scripts/check_no_generated_artifacts.sh
```

Scheduled fixture probes run in GitHub Actions via `.github/workflows/scheduled-probes.yml`.

## API Contract

- Base path: `/api/v1`
- Success envelope: `{"data": ..., "meta": {"request_id": "..."}}`
- Error envelope: `{"error": {"code": "...", "message": "...", "details": ...}, "meta": {"request_id": "..."}}`

### Publications semantics

- `GET /api/v1/publications` supports `mode=all|unread|latest` (plus temporary alias `mode=new`).
- `unread` = actionable read-state (`is_read=false`).
- `latest` = discovery-state (`first seen in the latest completed check`).
- Response counters:
  - `unread_count`: unread publications in current scope.
  - `latest_count`: publications discovered in latest completed check.
  - `new_count`: compatibility alias for `latest_count` (temporary).
