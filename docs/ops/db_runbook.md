# Database Operations Runbook

This runbook defines backup, restore, and verification procedures for the
PostgreSQL database used by `scholarr`.

## Objectives

- Keep data loss bounded via scheduled backups.
- Provide repeatable restore procedures.
- Verify backups by running regular restore drills.

Recommended starting targets:

- `RPO`: 24 hours (maximum acceptable data loss).
- `RTO`: 60 minutes (maximum acceptable restore time).

## Backup Strategy

Use logical backups from the running `db` compose service.

- Custom-format backup (recommended for restore flexibility):

```bash
scripts/db/backup_full.sh
```

- Plain SQL backup:

```bash
scripts/db/backup_full.sh --plain
```

Optional environment variables:

- `BACKUP_DIR`: destination directory (default: `<repo>/backups`)
- `BACKUP_PREFIX`: backup filename prefix (default: `scholarr`)
- `USE_DEV_COMPOSE=1`: include `docker-compose.dev.yml`

## Restore Strategy

Restore from a `.dump` (custom format) or `.sql` file into the running `db`
compose service.

- Restore without schema wipe:

```bash
scripts/db/restore_dump.sh --file backups/scholarr_20260220T120000Z.dump
```

- Restore with full `public` schema reset:

```bash
scripts/db/restore_dump.sh --file backups/scholarr_20260220T120000Z.dump --wipe-public
```

## Safety Checklist Before Restore

1. Pause writes (stop app/scheduler or set maintenance mode).
2. Create a fresh pre-restore backup.
3. Validate target dump checksum/size.
4. Confirm operator, scope, and rollback plan.

## Post-Restore Verification

1. Run migrations head check.
2. Run health endpoint checks.
3. Verify table row counts for core tables:
   - `users`
   - `scholar_profiles`
   - `publications`
   - `scholar_publications`
   - `crawl_runs`
4. Run integrity report and require zero failures:

```bash
python3 scripts/db/check_integrity.py
```

5. Run API smoke checks for scholars/publications/runs pages.

## Data Cleanup and Repair

Use the audited repair job for scholar-publication relinking cleanup:

```bash
python3 scripts/db/repair_publication_links.py --user-id <id> --requested-by "<operator>" --apply
```

Dry-run first, then re-run with `--apply` once scope and summary counts match expectation.

If cleanup changes schema assumptions, follow `docs/ops/migration_checklist.md` before any migration rollout.

## Restore Drill Cadence

- Run at least one full restore drill per month.
- Record:
  - backup artifact used,
  - restore start/end timestamps,
  - issues encountered,
  - achieved `RTO`.
