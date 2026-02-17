# scholarr Agent Handbook

This file is the consolidated source of truth for project scope, constraints, scrape contract, and UI implementation flow.

Raw probe artifacts in `planning/scholar_probe_tmp/notes/*.json` and `planning/scholar_probe_tmp/notes/*.md` remain historical evidence and fixture references.

## 1. Product Objective

- Build a self-hosted scholar tracking system ("scholarr") with reliable, low-cost scraping and clear, actionable UI.
- Keep the MVP scope intentionally small.
- Prioritize reliability and ease of use over advanced/fancy processing.

## 2. Locked Constraints and Preferences

- Multi-user system with strict tenant isolation.
- Users are admin-created only.
- Users can change their own password.
- Admin features are shown only to admin users.
- Same-origin cookie session model with CSRF protection.
- Container-first development workflow (`docker compose`, `uv`).
- Test while developing; avoid shipping untested flows.
- Keep backend modular and DRY.
- UI is being rebuilt from scratch against API contracts.

## 3. Current Backend Architecture

- Runtime: Python + FastAPI.
- DB: PostgreSQL + SQLAlchemy + Alembic migrations.
- Scheduler: background scheduler + continuation queue processing.
- Auth:
  - Argon2 password hashing.
  - Session cookie (`HttpOnly`, `SameSite=Lax`, secure flag configurable).
  - CSRF required for unsafe methods via `X-CSRF-Token`.
- Logging:
  - structured request logging with request IDs.
  - redaction controls for sensitive fields.

## 4. Scraping Contract (Probe-Based)

Status: sufficient for MVP implementation with graceful degradation.

Target endpoint:
- `https://scholar.google.com/citations?hl=en&user=<scholar_id>`

Primary selectors:
- Row: `tr.gsc_a_tr`
- Title/link: `a.gsc_a_at`
- Citation count: `a.gsc_a_ac`
- Year: `span.gsc_a_h` (fallback regex on year cell text)
- Metadata lines: first/second `div.gs_gray` -> authors/venue
- Cluster ID: from `citation_for_view=<user>:<cluster_id>` in title URL

Required parser states:
- `ok`
- `no_results`
- `blocked_or_captcha`
- `layout_changed`
- `network_error`

Required page flags:
- `has_show_more_button`
- `articles_range`

Quality assumptions from probe:
- title/cluster_id/citation/authors coverage observed near 100%
- year and venue may be missing and must remain nullable

Guardrails:
- Never crash the full run when one scholar fails.
- Persist structured failure/debug information for diagnosis.
- Handle inaccessible/redirected IDs as states, not exceptions.

## 5. Current API Scope

Base path: `/api/v1`

Envelope model:
- success: `{"data": ..., "meta": {"request_id": "..."}}`
- error: `{"error": {"code": "...", "message": "...", "details": ...}, "meta": {"request_id": "..."}}`

Auth/session:
- `GET /api/v1/auth/csrf`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/change-password`
- `POST /api/v1/auth/logout`

Admin users:
- `GET /api/v1/admin/users`
- `POST /api/v1/admin/users`
- `PATCH /api/v1/admin/users/{id}/active`
- `POST /api/v1/admin/users/{id}/reset-password`

Scholars:
- `GET /api/v1/scholars`
- `POST /api/v1/scholars`
- `PATCH /api/v1/scholars/{id}/toggle`
- `DELETE /api/v1/scholars/{id}`

Settings:
- `GET /api/v1/settings`
- `PUT /api/v1/settings`

Runs/diagnostics/queue:
- `GET /api/v1/runs`
- `GET /api/v1/runs/{id}`
- `POST /api/v1/runs/manual` (`Idempotency-Key` supported)
- `GET /api/v1/runs/queue/items`
- `POST /api/v1/runs/queue/{id}/retry`
- `POST /api/v1/runs/queue/{id}/drop`
- `DELETE /api/v1/runs/queue/{id}`

Publications:
- `GET /api/v1/publications`
- `POST /api/v1/publications/mark-all-read`

Ops:
- `GET /healthz`

## 6. Required UI Behavior (MVP)

Core UX entities:
- scholars
- publications (`all` and `new`)
- runs + run diagnostics
- queue visibility/actions
- settings/account
- admin users (role-gated)

Critical semantics:
- Keep `is_new_in_latest_run` separate from `is_read`.
- First-time ingestion should not imply user read-state.
- Surface partial runs and warnings clearly.
- Show loading, empty, and error states explicitly.

## 7. UI Information Architecture

Public:
- Login

Authenticated:
- Dashboard
- Scholars
- Publications
- Settings
- Admin Users (admin only)

## 8. End-to-End UI Flow Plan

## 8.1 Session bootstrap

1. On load call `GET /api/v1/auth/csrf`.
2. Call `GET /api/v1/auth/me`.
3. Route to login or dashboard based on auth state.

## 8.2 Login/logout

1. Login form submits `POST /api/v1/auth/login` with `X-CSRF-Token`.
2. Store CSRF token from response for future unsafe requests.
3. Logout calls `POST /api/v1/auth/logout`.

## 8.3 Dashboard



## 8.4 Scholars

1. List via `GET /api/v1/scholars`.
2. Add/toggle/delete actions mapped to scholar endpoints.
3. Per-row quick links:
   - all publications filtered by scholar
   - new publications filtered by scholar

## 8.5 Publications

## 8.6 Runs and diagnostics (admin)

1. List runs from `GET /api/v1/runs`.
2. Run details from `GET /api/v1/runs/{id}`:
   - scholar result state/reason
   - warnings
   - page logs + attempt logs
   - debug metadata
3. Queue operations from queue endpoints (`retry`, `drop`, `clear`).

## 8.7 Settings + account

1. User ingest settings from `/api/v1/settings`.
2. Password change via `/api/v1/auth/change-password`.

## 8.8 Admin user management

1. Show section only when `current_user.is_admin=true`.
2. Use admin user endpoints for create/activate/deactivate/reset password.

## 9. Development Method

- API-contract-first frontend.
- Vertical slices (complete flow before moving on).
- Shared API client module:
  - always send credentials
  - inject CSRF header for unsafe methods
  - normalize envelope parsing and error handling
- Keep frontend modules separate (`auth`, `scholars`, `publications`, `runs`, `settings`, `admin`).
- Write tests while implementing each slice.

## 10. Definition of Done (UI Readiness)

- All main flows above implemented and mapped to existing API endpoints.
- Role-gated admin experience enforced in UI.
- Distinct new-vs-read publication semantics visible.
- Run/queue diagnostics visible and actionable.
- Reliable loading/empty/error states with request-id surfaced for support.
- No dependence on removed server-rendered UI layer.

## 11. Open Items (Known Future Work)

- Scholar discovery by real name (search Google Scholar candidates, select one, then add scholar ID).
- API contract freeze/changelog discipline for external UI clients.
- Additional API-first smoke coverage for end-to-end UI critical flows.
