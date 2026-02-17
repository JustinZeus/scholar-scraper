# Scholar Scrape Probe Report

Generated UTC: `2026-02-16T18:22:18.839668+00:00`
Run fixtures dir: `planning/scholar_probe_tmp/fixtures/run_20260216T182157Z`

## Robots Snapshot

```text
User-agent: *
Disallow: /search
Disallow: /index.html
Disallow: /scholar
Disallow: /citations?
Allow: /citations?user=
Disallow: /citations?*cstart=
Disallow: /citations?user=*%40
Disallow: /citations?user=*@
Allow: /citations?view_op=list_classic_articles
Allow: /citations?view_op=mandates_leaderboard
Allow: /citations?view_op=metrics_intro
Allow: /citations?view_op=new_profile
Allow: /citations?view_op=sitemap
Allow: /citations?view_op=top_venues

User-agent: Twitterbot
Disallow:

User-agent: facebookexternalhit
Disallow:

User-agent: PetalBot
Disallow: /
```

## Fetch Summary

| Source | Status Code | Status/Error | Final URL |
| --- | --- | --- | --- |
| `robots` | 200 | ok | `https://scholar.google.com/robots.txt` |
| `profile_amIMrIEAAAAJ` | 200 | ok | `https://scholar.google.com/citations?hl=en&user=amIMrIEAAAAJ` |
| `profile_P1RwlvoAAAAJ` | 200 | ok | `https://scholar.google.com/citations?hl=en&user=P1RwlvoAAAAJ` |
| `profile_RxmmtT8AAAAJ` | 200 | ok | `https://scholar.google.com/citations?hl=en&user=RxmmtT8AAAAJ` |
| `profile_LZ5D_p4AAAAJ` | 200 | ok | `https://scholar.google.com/citations?hl=en&user=LZ5D_p4AAAAJ` |
| `profile_AAAAAAAAAAAA` | 200 | ok | `https://accounts.google.com/v3/signin/identifier?continue=https%3A%2F%2Fscholar.google.com%2Fcitations%3Fhl%3Den%26user%3DAAAAAAAAAAAA&dsh=S-568466874%3A1771266138494353&hl=en&ifkv=ASfE1-pK1BK8frcmUfumfUYfZZe1iJXbTGg6TCfyR-Q1ErPAopCpUGy_sEwLdvOICVCsiXsIJbFm1Q&service=citations&flowName=GlifWebSignIn&flowEntry=ServiceLogin` |

## Parse Summary

| Source | Parse Status | Profile | Publications | Warnings |
| --- | --- | --- | --- | --- |
| `profile_AAAAAAAAAAAA` | `blocked_or_captcha` | - | 0 | no_rows_detected |
| `profile_LZ5D_p4AAAAJ` | `ok` | Doaa Elmatary | 12 | - |
| `profile_P1RwlvoAAAAJ` | `ok` | WENRUI ZUO | 5 | - |
| `profile_RxmmtT8AAAAJ` | `ok` | K. Srinivasan | 20 | - |
| `profile_amIMrIEAAAAJ` | `ok` | Bangar Raju Cherukuri | 20 | - |

## Field Coverage

Total parsed publication rows: **57**

| Field | Present | Coverage |
| --- | --- | --- |
| `title` | 57 | 100.0% |
| `cluster_id` | 57 | 100.0% |
| `year` | 56 | 98.2% |
| `citation_count` | 57 | 100.0% |
| `authors_text` | 57 | 100.0% |
| `venue_text` | 54 | 94.7% |

## Parser Contract Recommendation

- Primary row marker: `tr.gsc_a_tr`.
- Title anchor marker: `a.gsc_a_at`; derive `cluster_id` from `citation_for_view` query token.
- Metadata text markers: first/second `div.gs_gray` per row for authors and venue.
- Year marker fallback: classes containing `gsc_a_h` or `gsc_a_y` and 4-digit year regex.
- Failure states to persist: `ok`, `no_results`, `blocked_or_captcha`, `layout_changed`, `network_error`.

## Future-Proofing Notes

- Keep raw HTML fixture snapshots and update parser tests on DOM drift.
- Treat blocked pages as retriable with backoff, not parser errors.
- Add marker-count assertions in CI to catch silent layout shifts early.
- Use explicit parse status per run/scholar so automation can degrade gracefully.
