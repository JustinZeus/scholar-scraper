# Domain Boundaries

## Data Model Rules

- Scholar tracking is user-scoped.
- Publications are global/deduplicated records.
- Read/favorite/visibility state stays on scholar-publication link rows.

## Service Boundaries

Canonical business logic belongs in `app/services/domains/*`.

- `app/services/domains/ingestion/*`: run orchestration, continuation queue, scheduler, and scrape safety.
- `app/services/domains/scholar/*`: fail-fast scholar parsing and source fetch adapters.
- `app/services/domains/scholars/*`: scholar CRUD, profile image, and name-search controls.
- `app/services/domains/publications/*`: listing/read-state, favorite toggles, enrichment scheduling, and retry paths.
- `app/services/domains/crossref/*` + `app/services/domains/unpaywall/*`: DOI/OA enrichment with bounded pacing.
- `app/services/domains/runs/*`: run history and continuation queue operations.
- `app/services/domains/portability/*`: import/export workflows.

## Frontend Behavior Notes

- Mobile primary nav is in a left drawer and closes on route change or logout.
- Long list views use internal scroll containers.
- Name search remains intentionally constrained due upstream anti-bot behavior; production onboarding should prefer scholar ID/profile URL.
