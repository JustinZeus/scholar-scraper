# API Contract

## Envelope Invariant

All API responses under `/api/v1` use one of these envelopes:

- Success: `{"data": ..., "meta": {"request_id": "..."}}`
- Error: `{"error": {"code": "...", "message": "...", "details": ...}, "meta": {"request_id": "..."}}`

`meta.request_id` must be present for success and error responses.

## Publications Semantics

- `GET /api/v1/publications` supports `mode=all|unread|latest`.
- `mode=new` is currently accepted as a compatibility alias for `latest`.
- Pagination controls: `page`, `page_size` (with backward-compatible `limit`/`offset` support).
- Pagination fields in response: `page`, `page_size`, `has_prev`, `has_next`, `total_count`.
- `unread` represents read-state (`is_read=false`).
- `latest` represents discovery-state (`first seen in the latest completed run`).

Publication payloads expose:
- `pub_url` (canonical scholar detail URL)
- `doi` (normalized DOI)
- `pdf_url` (resolved OA PDF when available)

## Scholar Portability

- `GET /api/v1/scholars/export` exports tracked scholars and scholar-publication link state.
- `POST /api/v1/scholars/import` imports that payload while preserving global publication deduplication.
