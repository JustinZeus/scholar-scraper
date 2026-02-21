# Migration Checklist

Use this checklist for every schema/data migration.

## 1. Design Review

- Define change type: `expand`, `backfill`, `contract`.
- Document expected lock behavior and index impact.
- Confirm backward compatibility with currently deployed app version.
- Define rollback strategy before implementation.

## 2. Pre-Migration Controls

- Capture a fresh backup before applying migration.
- Confirm migration head revision and working tree cleanliness.
- Prepare validation queries for new/changed tables and indexes.
- Identify high-risk tables (large row count, hot write paths).

## 3. Implementation Standards

- Keep migrations idempotent when feasible.
- Prefer additive steps first (`nullable`, new index, new table).
- For destructive changes, separate into later contract migration.
- Avoid large blocking rewrites in a single deployment step.

## 4. Verification

- Apply migration in staging against production-like snapshot.
- Verify:
  - expected tables/columns/indexes,
  - app startup and health endpoint,
  - affected API flows,
  - data consistency queries.

## 5. Rollout and Recovery

- Apply migration during planned window.
- Monitor logs/errors and DB metrics during rollout.
- If rollback needed:
  - follow downgrade/recovery runbook,
  - restore from backup if downgrade is unsafe,
  - document incident timeline.

## 6. Post-Migration Tasks

- Update `README.md` / `.env.example` / ops docs.
- Add/update integration tests for new schema assumptions.
- Record migration notes in changelog.
