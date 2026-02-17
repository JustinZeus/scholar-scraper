# MVP Implementation Reminders (From Scholar Probe)

Last validated probe run: `planning/scholar_probe_tmp/notes/probe_report_run_20260216T182334Z.md`.

## Decision: Are we ready?

Yes, for the scoped MVP.

- We have stable selectors and field coverage for first-page profile parsing.
- We have explicit failure modes for blocked/inaccessible pages.
- We have enough fixtures to start parser + ingestion tests immediately.

Not guaranteed (and intentionally out of MVP):

- Full historical completeness from profile pagination.
- Robots currently disallows `citations?*cstart=`; treat deep pagination as out of scope unless policy changes.

## Non-negotiables

- Keep app container-first (`docker compose`) and test while developing.
- Keep feature scope small; prefer deterministic behavior over clever scraping.
- Never crash a whole run because one scholar page fails.
- Preserve strict tenant isolation for all run/output/read-state data.

## Scraping Contract

Target URL:

- `https://scholar.google.com/citations?hl=en&user=<scholar_id>`

Primary parse markers:

- Row: `tr.gsc_a_tr`
- Title/link: `a.gsc_a_at`
- Citation count: `a.gsc_a_ac`
- Year: `span.gsc_a_h` (fallback year regex)
- Metadata lines: first/second `div.gs_gray` => authors/venue
- Cluster id from `citation_for_view=<user>:<cluster_id>`

## Required Parse States

Use and persist one of:

- `ok`
- `no_results`
- `blocked_or_captcha`
- `layout_changed`
- `network_error`

Plus these page-level flags:

- `has_show_more_button`
- `articles_range`

## Data Quality Expectations

Observed from probe sample:

- `title`: 100%
- `cluster_id`: 100%
- `citation_count`: 100%
- `authors_text`: 100%
- `year`: 98.2%
- `venue_text`: 94.7%

Implications:

- `year` and `venue_text` must remain nullable.
- Dedupe must not depend solely on `year`/`venue_text` presence.

## Run Semantics

- First successful run per scholar = baseline.
- If `has_show_more_button=true`, label result as partial in run status/UI.
- Invalid/inaccessible scholar IDs are expected and should become structured run errors, not exceptions.

## Testing Priorities (Do Before Feature Expansion)

- Fixture parser unit tests using probe HTML snapshots.
- Parse-state classification tests (ok/blocked/layout/no_results).
- Dedupe integration tests (`cluster_id` first, fingerprint fallback).
- Tenant isolation tests for run records and read-state.
- Smoke test for manual run path through Docker.

## Stop Conditions

Pause implementation and re-probe if:

- Selector markers drop out unexpectedly.
- Login/redirect pages become frequent for valid IDs.
- Robots policy for profile endpoints changes.

