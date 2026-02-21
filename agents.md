# AI Agent Instructions: Scholarr

Adhere strictly to these constraints.

## 1. Coding Standards (Strict Enforcement)
* **Function Length:** Maximum 50 lines of code per function. Break down complex logic into small, testable, single-responsibility functions.
* **DRY (Don't Repeat Yourself):** Abstract repetitive logic immediately. No duplicate boilerplate for database queries, API responses, or error handling.
* **Negative Space Programming:** Utilize explicit assertions and constraints to define invalid states. Fail fast and early. Do not allow silent failures or cascading malformed data, especially in DOM parsing.
* **Cyclomatic Complexity:** Flatten logic. Use early returns and guard clauses instead of deep nesting.

## 2. Domain Architecture & Data Model
* **Data Isolation:** Scholar tracking is **user-scoped**. Validate mapping/join tables; never assume global links between users and Scholar IDs.
* **Data Deduplication:** Publications are **global records**. Deduplicate via Scholar cluster ID and normalized fingerprinting prior to database insertion.
* **State Management:** Visibility and "read/unread" states exist exclusively on the scholar-publication link table, not the global publication table.
* **API Contract:** Exact envelope format required:
    * Success: `{"data": ..., "meta": {"request_id": "..."}}`
    * Error: `{"error": {"code": "...", "message": "...", "details": ...}, "meta": {"request_id": "..."}}`

## 3. Scrape Safety & Rate Limiting (Immutable)
These limits prevent IP bans and are not to be optimized away.
* **Minimum Delay:** Enforce `INGESTION_MIN_REQUEST_DELAY_SECONDS` (default 2s) between all external requests.
* **Anti-Detection:** Default to direct ID or profile URL ingestion. Name searches trigger CAPTCHAs.
* **Cooldowns:** Respect `INGESTION_SAFETY_COOLDOWN_BLOCKED_SECONDS` (1800s) and `INGESTION_SAFETY_COOLDOWN_NETWORK_SECONDS` (900s) upon threshold breaches.

## 4. Current Environment & Stack
* **Backend:** Python 3.12+, FastAPI, SQLAlchemy (Async/asyncpg), Alembic.
* **Frontend:** TypeScript, Vue 3, Vite.
* **Infrastructure:** Multi-stage Docker.

## 5. Domain Service Boundaries
* **Strict Modularity:** Flat files in the `app/services/` root are strictly prohibited. All business logic and routing must reside exclusively within `app/services/domains/`.
* **`app/services/domains/scholar/*`:** Parser contract is fail-fast. Layout drift must emit explicit exceptions and `layout_*` reasons/warnings. Never allow silent partial success.
* **`app/services/domains/ingestion/application.py`:** Orchestrates ingestion runs; validate parser outputs before persistence; enforce publication candidate constraints before upsert.
* **`app/services/domains/publications/*`:** Publication list/read-state query layer. Includes `doi` + `pdf_url` fields for UI consumption, enforces non-blocking lazy OA enrichment scheduling on list reads, and exposes per-publication PDF retry behavior.
* **`app/services/domains/crossref/*`:** DOI discovery fallback module. Must use bounded/paced lookups to avoid burst traffic and 429 responses.
* **`app/services/domains/unpaywall/*`:** OA resolver by DOI only (best OA location + PDF URL extraction). Do not use Google Scholar for PDF resolution to avoid N+1 scrape amplification.
* **`app/services/domains/portability/*`:** Handles JSON import/export for user-scoped scholars and scholar-publication link state while preserving global publication dedup rules.
* **`app/services/domains/ingestion/scheduler.py`:** Owns automatic runs and continuation queue retries/drops; do not bypass safety gate or cooldown logic.


## 6. UI rules
Make sure to properly integrate tailwind in combination with the preset theming
Clarity through both styling and language are a priority. all UI elements need to have a proper reason for existing.