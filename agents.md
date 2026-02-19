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

## 5. Refactored Service Boundaries (Current)
* **`app/services/scholar_parser.py`:** Parser contract is fail-fast. Layout drift must emit explicit `layout_*` reasons/warnings, never silent partial success.
* **`app/services/ingestion.py`:** Orchestrates ingestion runs; validate parser outputs before persistence; enforce publication candidate constraints before upsert.
* **`app/services/publications.py`:** Publication list/read-state query layer; include both `pub_url` and `pdf_url` for UI consumption.
* **`app/services/import_export.py`:** Handles JSON import/export for user-scoped scholars and scholar-publication link state while preserving global publication dedup rules.
* **`app/services/scheduler.py`:** Owns automatic runs and continuation queue retries/drops; do not bypass safety gate or cooldown logic.
