# Probe Findings -> Phase 1 Input

Generated from live probe run: `run_20260216T182334Z`.

## What is stable enough to build on

- Public profile endpoint works for anonymous access:
  - `GET /citations?hl=en&user=<scholar_id>`
- Core row structure is present and parseable:
  - row: `tr.gsc_a_tr`
  - title + detail URL: `a.gsc_a_at`
  - citation count: `a.gsc_a_ac`
  - year: `span.gsc_a_h` (fallback: `td.gsc_a_y` text regex)
  - metadata lines: first/second `div.gs_gray` => authors/venue
- `cluster_id` can be extracted reliably from `citation_for_view=<user>:<cluster_id>` in title URLs.

## What can break / where to degrade gracefully

- Invalid or inaccessible profile IDs may redirect to Google sign-in page.
  - Treat as `blocked_or_captcha` / `inaccessible` state, not parser crash.
- `Show more` is present for tested profiles.
  - We currently parse first page only.
  - Because robots currently disallows `citations?*cstart=`, deep pagination should not be assumed.
- Some rows are missing year or venue text.
  - Keep nullable fields and avoid failing dedupe for these gaps.

## Observed quality from probe

- Parsed publication rows: 57 across 4 accessible profiles.
- Field coverage:
  - title: 100%
  - cluster_id: 100%
  - citation_count: 100%
  - authors_text: 100%
  - year: 98.2%
  - venue_text: 94.7%

## Recommended parser contract for implementation

- Input -> `PublicationCandidate`
  - `title` (required)
  - `cluster_id` (required when present in URL; expected high coverage)
  - `year` (nullable)
  - `citation_count` (nullable/int default fallback 0)
  - `authors_text` (nullable)
  - `venue_text` (nullable)
  - `title_url` (nullable)
- Page-level parse status enum:
  - `ok`, `no_results`, `blocked_or_captcha`, `layout_changed`, `network_error`
- Page-level flags:
  - `has_show_more_button`
  - `articles_range` string (e.g. `Articles 1–20`)

## Immediate test plan unlocked by this probe

- Add fixture-driven unit tests using captured HTML from `fixtures/run_20260216T182334Z`.
- Add assertions for:
  - row count > 0 on known-good fixtures
  - profile name extraction
  - cluster_id extraction from title URLs
  - nullable handling for year/venue
  - blocked/inaccessible page classification
  - show-more partial warning classification

## Phase 1 implementation guardrails

- Keep requests low-rate with jitter and explicit timeout.
- Persist parser status per scholar run.
- If `has_show_more_button=True`, mark run as partial and show this in UI.
- Never fail entire run because one scholar page is blocked or malformed.

