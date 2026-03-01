# AI Agent Instructions: Scholarr

Adhere strictly to these constraints when working on this codebase.

## 1. Code Quality

- **Function length:** 50 lines max. Extract helpers ruthlessly.
- **File length:** 400 lines target, 600 lines hard ceiling. Files above this must be decomposed before adding more code.
- **DRY:** Abstract repeated logic immediately. No duplicate boilerplate for queries, responses, or error handling.
- **Negative space programming:** Fail fast with explicit assertions and guard clauses. No silent failures, especially in DOM parsing.
- **Cyclomatic complexity:** Flatten with early returns. No deep nesting. No magic numbers.
- **No dead code:** Do not leave commented-out code, unused imports, or backward-compatibility shims. Delete cleanly.
- **Variable naming:** Any variable outside of a lambda functions or iterators should be descriptive. Code should be readable for maintainers.

## 2. Architecture

### Data Model

- Scholar tracking is **user-scoped**. Never assume global links between users and Scholar IDs.
- Publications are **global, deduplicated records**. Deduplicate via cluster ID and normalized fingerprinting.
- Read/unread, favorites, and visibility state live on the **scholar-publication link**, not the publication.

### Service Boundaries

All business logic lives in `app/services/<domain>/`. No flat files in `app/services/` root. Each domain owns its application service, types, and helpers.

### API Envelope

All `/api/v1` responses use this exact envelope:

```
Success: {"data": ..., "meta": {"request_id": "..."}}
Error:   {"error": {"code": "...", "message": "...", "details": ...}, "meta": {"request_id": "..."}}
```

Use the Pydantic envelope schemas in `app/api/schemas.py`. Do not construct raw dicts.

## 3. Scrape Safety (Immutable)

These constraints prevent IP bans. They are not tunable to zero and must not be optimized away.

- Enforce `INGESTION_MIN_REQUEST_DELAY_SECONDS` (default 2s) between all external requests.
- Default to direct ID or profile URL ingestion. Name searches trigger CAPTCHAs.
- Respect `INGESTION_SAFETY_COOLDOWN_BLOCKED_SECONDS` (1800s) and `INGESTION_SAFETY_COOLDOWN_NETWORK_SECONDS` (900s) upon threshold breaches.

## 4. Logging

Use `structured_log()` from `app/logging_utils.py` for all domain logging. Do not use raw `logger.info()` / `logger.warning()` calls.

```python
from app.logging_utils import structured_log

structured_log(logger, "info", "ingestion.run_started", user_id=user_id, scholar_count=count)
```

Every event name should be dot-namespaced to its domain (e.g., `arxiv.cache_hit`, `ingestion.safety_cooldown_entered`).

## 5. Stack & Tooling

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2.0 (async/asyncpg), Alembic
- **Frontend:** TypeScript, Vue 3, Vite, Tailwind CSS
- **Infrastructure:** Multi-stage Docker, Docker Compose
- **Package manager:** `uv` (used in Dockerfile and CI; `uv run` prefix for all commands)
- **Linting:** `ruff check .` and `ruff format --check .` (config in `pyproject.toml`)
- **Type checking:** `mypy app/`
- **Versioning:** python-semantic-release with conventional commits

## 6. Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>
```

Types: `feat`, `fix`, `docs`, `ci`, `refactor`, `test`, `chore`, `perf`.

## 7. Testing & Quality Gates

All **local development** commands run inside containers. Do not run bare `npm`, `pytest`, or `ruff` on the host. CI workflows (`.github/workflows/`) use bare runners with `uv` and `npm` directly — this is intentional since CI has no Docker-in-Docker dependency.

### Backend

```bash
# Unit tests (default, excludes integration)
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app python -m pytest

# Integration tests
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app python -m pytest -m integration

# Linting
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app ruff check .
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app ruff format --check .

# Type checking
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app mypy app/
```

Pytest markers: `integration`, `db`, `migrations`, `schema`, `smoke`.

### Frontend

```bash
# Type checking
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm frontend npm run typecheck

# Unit tests
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm frontend npm run test:run

# Lint
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm frontend npm run lint

# Production build
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm frontend npm run build
```

All four gates must pass before a PR is considered ready.

## 8. Frontend

- Use the tokenized theme system (`frontend/src/theme/presets/`). Do not hardcode colors.
- Integrate Tailwind with preset theme tokens. Reference `frontend/scripts/check_theme_tokens.mjs` for enforcement.
- Every UI element must have a clear purpose. Clarity through styling and language.
