# Scrape Safety Runbook

This runbook covers operational handling for scrape safety cooldowns, threshold alerts, and blocked-IP events.

## Key Signals

Use structured log `event` fields (recommended with `LOG_FORMAT=json`):

- `ingestion.safety_policy_blocked_run_start`
- `ingestion.safety_cooldown_entered`
- `ingestion.safety_cooldown_cleared`
- `ingestion.alert_blocked_failure_threshold_exceeded`
- `ingestion.alert_network_failure_threshold_exceeded`
- `ingestion.alert_retry_scheduled_threshold_exceeded`
- `api.runs.manual_blocked_policy`
- `api.runs.manual_blocked_safety`
- `scheduler.run_skipped_safety_cooldown`
- `scheduler.run_skipped_safety_cooldown_precheck`
- `scheduler.queue_item_deferred_safety_cooldown`

Each event includes metric-style fields (`metric_name`, `metric_value`) for straightforward log-based alert rules.

## Recommended Alert Rules

- Cooldown enters:
  - Trigger on `event=ingestion.safety_cooldown_entered`.
- Repeated start blocks:
  - Trigger on high rate of `event=api.runs.manual_blocked_safety`.
- Threshold trips:
  - Trigger on any of:
    - `ingestion.alert_blocked_failure_threshold_exceeded`
    - `ingestion.alert_network_failure_threshold_exceeded`
    - `ingestion.alert_retry_scheduled_threshold_exceeded`
- Scheduler pressure:
  - Trigger on sustained `scheduler.queue_item_deferred_safety_cooldown`.

## If Your IP Appears Blocked

Symptoms:

- cooldown reason `blocked_failure_threshold_exceeded`
- parse state `blocked_or_captcha`
- redirects toward Google account sign-in flows

Actions:

1. Stop manual retries immediately.
2. Let cooldown expire; do not spam retriggers.
3. Increase `INGESTION_MIN_REQUEST_DELAY_SECONDS` and user request delay values.
4. Reduce concurrency pressure (keep one scheduler instance).
5. Keep name-search disabled/WIP for now if login-gated responses persist.
6. Resume with a small monitored run and verify blocked rate drops.

Avoid:

- aggressive rapid retries
- rotating through risky scraping patterns that increase challenge rates
- bypass/captcha-solving workflows that may violate source platform rules

## Environment Controls

Policy floors and safety controls:

- `INGESTION_MIN_REQUEST_DELAY_SECONDS`
- `INGESTION_MIN_RUN_INTERVAL_MINUTES`
- `INGESTION_ALERT_BLOCKED_FAILURE_THRESHOLD`
- `INGESTION_ALERT_NETWORK_FAILURE_THRESHOLD`
- `INGESTION_ALERT_RETRY_SCHEDULED_THRESHOLD`
- `INGESTION_SAFETY_COOLDOWN_BLOCKED_SECONDS`
- `INGESTION_SAFETY_COOLDOWN_NETWORK_SECONDS`
- `INGESTION_MANUAL_RUN_ALLOWED`
- `INGESTION_AUTOMATION_ALLOWED`

Apply stricter values first, then relax slowly only after sustained healthy runs.
