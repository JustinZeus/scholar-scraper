# scholarr

Container-first, self-hosted scholar tracking in the spirit of the `*arr` ecosystem, with strict multi-user isolation and an intentionally small operational footprint.

## Current Scope

- Admin-managed users only (no public signup)
- Session auth with CSRF protection and login rate limiting
- Per-user scholar tracking list (add, enable/disable, delete)
- Per-user automation settings
- Manual per-user ingestion runs from dashboard
- Per-user run history and "new since last run" publication stream
- Publications library view with `new` and `all` modes plus scholar filtering
- Dedicated run diagnostics pages (`/runs`, `/runs/{id}`) with failed-only filtering
- Continuation queue visibility + controls on runs page (`retry`, `drop`, `clear`)
- Baseline-aware discovery tracking (`new` = discovered in latest completed run)
- Read state is user-controlled (`Mark All Read`), including baseline items
- Multi-page profile ingestion (`cstart`) to capture full publication lists
- Dashboard rendered via a presentation-layer view model and section template registry
- Structured application logging with request IDs and field redaction
- Ingestion overlap guard via Postgres advisory locks
- Network-error retry support for ingestion attempts
- Automatic continuation queue for resumable/limit-hit scholar runs
- Background scheduler for per-user automatic runs
- User self-service password changes
- Admin user management (create users, activate/deactivate, reset passwords)
- PostgreSQL + Alembic migrations + containerized test workflow
- Versioned backend API (`/api/v1`) for frontend decoupling (same-origin cookie session)

## Tech Stack

- Python 3.12+
- FastAPI
- PostgreSQL 15+
- SQLAlchemy 2 + Alembic
- Jinja2 templates + modular theme tokens
- `uv` for dependency and runtime workflow
- Docker / Docker Compose for development and CI parity

## Quick Start

1. Copy environment defaults:

```bash
cp .env.example .env
```

2. Bootstrap the first admin on startup (recommended for first run):

```bash
export BOOTSTRAP_ADMIN_ON_START=1
export BOOTSTRAP_ADMIN_EMAIL=admin@example.com
export BOOTSTRAP_ADMIN_PASSWORD=change-me-now
```

3. Start the stack:

```bash
docker compose up --build
```

4. Open:

- Login: `http://localhost:8000/login`
- Dashboard: `http://localhost:8000/`
- Healthcheck: `http://localhost:8000/healthz`

5. After first successful admin login, disable auto-bootstrap:

```bash
export BOOTSTRAP_ADMIN_ON_START=0
```

## Admin Bootstrap (Manual)

You can create/update an admin account without restarting the app:

```bash
docker compose run --rm app uv run python scripts/bootstrap_admin.py \
  --email admin@example.com \
  --password change-me-now \
  --force-password
```

Notes:
- If the user does not exist, this creates an active admin account.
- If the user exists, it ensures admin + active flags.
- `--force-password` resets the password for existing users.

## Test Workflow

- Integration/smoke tests run against `TEST_DATABASE_URL`.
- If `TEST_DATABASE_URL` is empty, test runs derive an isolated database from `DATABASE_URL` by appending `_test`.
- This keeps app data in `DATABASE_URL` untouched during test runs.
- Parser regression tests are pinned to captured real-world fixture pages in `tests/fixtures/scholar/regression`.

- Unit tests:

```bash
docker compose run --rm app uv run pytest tests/unit
```

- Integration tests:

```bash
docker compose run --rm app uv run pytest -m integration
```

- Smoke checks (container + DB + migration sanity):

```bash
./scripts/smoke_compose.sh
```

CI runs migration, unit, and integration checks on push/PR via `.github/workflows/ci.yml`.

## Scholar Ingestion Notes

- Current ingestion targets public profile pages: `/citations?user=<id>`.
- Runs are intentionally conservative and prioritize reliability over aggressive scraping.
- Ingestion follows pagination (`cstart`) to collect all reachable profile pages.
- If pagination cannot be completed (max pages hit, cursor stall, or page-state failure), the scholar result is marked partial with explicit debug context.
- Resumable partial/failure states are automatically queued and retried by the scheduler with bounded backoff.
- Queue items keep explicit status (`queued`, `retrying`, `dropped`) and last-error context for UI diagnostics.
- Failed scholar attempts persist structured debug context in `crawl_runs.error_log` (state reason, fetch metadata, marker evidence, and compact response excerpt).
- Only resumable states are retried automatically (`network_error` and continuation-eligible pagination truncations); blocked/layout states are recorded immediately as failures.

## API v1 (Frontend Prep)

- Base path: `/api/v1`
- Auth model: same-origin cookie session (no token auth added)
- CSRF model: required for unsafe methods (`POST`, `PUT`, `PATCH`, `DELETE`) via `X-CSRF-Token` header.
- Bootstrap CSRF via `GET /api/v1/auth/csrf` (works for anonymous and authenticated sessions).
- You can also fetch `csrf_token` from `GET /api/v1/auth/me` after login.
- Manual run idempotency is supported via `Idempotency-Key` header on `POST /api/v1/runs/manual`.
- Response envelopes:
  - Success: `{"data": ..., "meta": {"request_id": "..."}}`
  - Error: `{"error": {"code": "...", "message": "...", "details": ...}, "meta": {"request_id": "..."}}`
- Initial API domains exposed:
  - `auth`: `/auth/csrf`, `/auth/login`, `/auth/me`, `/auth/change-password`, `/auth/logout`
  - `admin users`: `/admin/users` (list/create), `/admin/users/{id}/active`, `/admin/users/{id}/reset-password`
  - `scholars`: list/create/toggle/delete
  - `settings`: get/update
  - `runs`: list/detail/manual trigger + queue list/retry/drop/clear
  - `publications`: list + mark-all-read
- Queue action semantics:
  - `retry` is valid only for dropped items; retrying/queued states return `409`.
  - `drop` returns the updated queue item (status `dropped`); dropping an already dropped item returns `409`.
  - `clear` only works for dropped items and returns `{queue_item_id, previous_status, status="cleared"}`.

## Logging

- Default output is concise console logs to stdout.
- Timestamp format is compact UTC: `YYYY-MM-DD HH:MM:SSZ`.
- Every request gets an `X-Request-ID` (propagated if caller provides one).
- Sensitive fields are redacted before log emission (`password`, `csrf_token`, `cookie`, etc.).
- Configure via env:
  - `LOG_LEVEL` (default `INFO`)
  - `LOG_FORMAT` (`console` or `json`, default `console`)
  - `LOG_REQUESTS` (`1`/`0`, default `1`)
  - `LOG_UVICORN_ACCESS` (`1`/`0`, default `0`)
  - `LOG_REQUEST_SKIP_PATHS` (comma-separated prefixes, default `/healthz,/static/`)
  - `LOG_REDACT_FIELDS` (comma-separated additional keys)
  - `SCHEDULER_ENABLED` (`1`/`0`, default `1`)
  - `SCHEDULER_TICK_SECONDS` (default `60`)
  - `INGESTION_NETWORK_ERROR_RETRIES` (default `1`)
  - `INGESTION_RETRY_BACKOFF_SECONDS` (default `1.0`)
  - `INGESTION_MAX_PAGES_PER_SCHOLAR` (default `30`)
  - `INGESTION_PAGE_SIZE` (default `100`)
  - `INGESTION_CONTINUATION_QUEUE_ENABLED` (`1`/`0`, default `1`)
  - `INGESTION_CONTINUATION_BASE_DELAY_SECONDS` (default `120`)
  - `INGESTION_CONTINUATION_MAX_DELAY_SECONDS` (default `3600`)
  - `INGESTION_CONTINUATION_MAX_ATTEMPTS` (default `6`)
  - `SCHEDULER_QUEUE_BATCH_SIZE` (default `10`)

## Optional Local `uv` Workflow

```bash
uv sync --extra dev
uv run pytest
uv run uvicorn app.main:app --reload
```

Update the lockfile after dependency changes:

```bash
uv lock
```

## Theming

- Theme registry: `app/theme.py`
- Semantic tokens: `app/static/theme.css`
- App styling: `app/static/app.css`
- Theme persistence: `app/static/theme.js`
- Dashboard presentation contract: `app/presentation/dashboard.py`

## Project Layout

```text
app/         FastAPI app, auth/security modules, templates, services, DB wiring, presentation view-models
app/web/     Router modules, shared web helpers, and request middleware
alembic/     Migration environment and versions
scripts/     Entrypoint, DB wait, bootstrap, smoke automation
tests/       Unit, integration, and smoke suites
```
