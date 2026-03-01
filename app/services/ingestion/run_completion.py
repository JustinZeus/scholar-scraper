from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from app.db.models import (
    CrawlRun,
    RunStatus,
    ScholarProfile,
)
from app.logging_utils import structured_log
from app.services.ingestion import safety as run_safety_service
from app.services.ingestion.constants import (
    FAILED_STATES,
    FAILURE_BUCKET_BLOCKED,
    FAILURE_BUCKET_INGESTION,
    FAILURE_BUCKET_LAYOUT,
    FAILURE_BUCKET_NETWORK,
    FAILURE_BUCKET_OTHER,
)
from app.services.ingestion.fingerprints import _build_body_excerpt
from app.services.ingestion.types import (
    RunAlertSummary,
    RunExecutionSummary,
    RunFailureSummary,
    RunProgress,
    ScholarProcessingOutcome,
)
from app.services.scholar.parser import ParsedProfilePage, ParseState
from app.services.scholar.source import FetchResult
from app.settings import settings

logger = logging.getLogger(__name__)


def int_or_default(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def classify_failure_bucket(*, state: str, state_reason: str) -> str:
    reason = state_reason.strip().lower()
    normalized_state = state.strip().lower()

    if normalized_state == ParseState.BLOCKED_OR_CAPTCHA.value or reason.startswith("blocked_"):
        return FAILURE_BUCKET_BLOCKED
    if normalized_state == ParseState.NETWORK_ERROR.value or reason.startswith("network_"):
        return FAILURE_BUCKET_NETWORK
    if normalized_state == ParseState.LAYOUT_CHANGED.value:
        return FAILURE_BUCKET_LAYOUT
    if normalized_state == "ingestion_error":
        return FAILURE_BUCKET_INGESTION
    return FAILURE_BUCKET_OTHER


def summarize_failures(
    *,
    scholar_results: list[dict[str, Any]],
) -> RunFailureSummary:
    failed_state_counts: dict[str, int] = {}
    failed_reason_counts: dict[str, int] = {}
    scrape_failure_counts: dict[str, int] = {}
    retries_scheduled_count = 0
    scholars_with_retries_count = 0
    retry_exhausted_count = 0
    for entry in scholar_results:
        retries_for_entry = max(0, int_or_default(entry.get("attempt_count"), 0) - 1)
        if retries_for_entry > 0:
            retries_scheduled_count += retries_for_entry
            scholars_with_retries_count += 1
        if str(entry.get("outcome", "")) != "failed":
            continue
        state = str(entry.get("state", "")).strip()
        if state not in FAILED_STATES:
            continue
        failed_state_counts[state] = failed_state_counts.get(state, 0) + 1
        reason = str(entry.get("state_reason", "")).strip()
        if reason:
            failed_reason_counts[reason] = failed_reason_counts.get(reason, 0) + 1
        bucket = classify_failure_bucket(state=state, state_reason=reason)
        scrape_failure_counts[bucket] = scrape_failure_counts.get(bucket, 0) + 1
        if state == ParseState.NETWORK_ERROR.value and retries_for_entry > 0:
            retry_exhausted_count += 1
    return RunFailureSummary(
        failed_state_counts=failed_state_counts,
        failed_reason_counts=failed_reason_counts,
        scrape_failure_counts=scrape_failure_counts,
        retries_scheduled_count=retries_scheduled_count,
        scholars_with_retries_count=scholars_with_retries_count,
        retry_exhausted_count=retry_exhausted_count,
    )


def build_alert_summary(
    *,
    failure_summary: RunFailureSummary,
    alert_blocked_failure_threshold: int,
    alert_network_failure_threshold: int,
    alert_retry_scheduled_threshold: int,
) -> RunAlertSummary:
    blocked_failure_count = int(failure_summary.scrape_failure_counts.get(FAILURE_BUCKET_BLOCKED, 0))
    network_failure_count = int(failure_summary.scrape_failure_counts.get(FAILURE_BUCKET_NETWORK, 0))
    blocked_threshold = max(1, int(alert_blocked_failure_threshold))
    network_threshold = max(1, int(alert_network_failure_threshold))
    retry_threshold = max(1, int(alert_retry_scheduled_threshold))
    alert_flags = {
        "blocked_failure_threshold_exceeded": blocked_failure_count >= blocked_threshold,
        "network_failure_threshold_exceeded": network_failure_count >= network_threshold,
        "retry_scheduled_threshold_exceeded": failure_summary.retries_scheduled_count >= retry_threshold,
    }
    return RunAlertSummary(
        blocked_failure_count=blocked_failure_count,
        network_failure_count=network_failure_count,
        blocked_failure_threshold=blocked_threshold,
        network_failure_threshold=network_threshold,
        retry_scheduled_threshold=retry_threshold,
        alert_flags=alert_flags,
    )


def apply_safety_outcome(
    *,
    user_settings: Any,
    run: CrawlRun,
    user_id: int,
    alert_summary: RunAlertSummary,
) -> None:
    pre_apply_state = run_safety_service.get_safety_event_context(
        user_settings,
        now_utc=datetime.now(UTC),
    )
    safety_state, cooldown_trigger_reason = run_safety_service.apply_run_safety_outcome(
        user_settings,
        run_id=int(run.id),
        blocked_failure_count=alert_summary.blocked_failure_count,
        network_failure_count=alert_summary.network_failure_count,
        blocked_failure_threshold=alert_summary.blocked_failure_threshold,
        network_failure_threshold=alert_summary.network_failure_threshold,
        blocked_cooldown_seconds=settings.ingestion_safety_cooldown_blocked_seconds,
        network_cooldown_seconds=settings.ingestion_safety_cooldown_network_seconds,
        now_utc=datetime.now(UTC),
    )
    if cooldown_trigger_reason is not None:
        structured_log(
            logger,
            "warning",
            "ingestion.safety_cooldown_entered",
            user_id=user_id,
            crawl_run_id=int(run.id),
            reason=cooldown_trigger_reason,
            blocked_failure_count=alert_summary.blocked_failure_count,
            network_failure_count=alert_summary.network_failure_count,
            blocked_failure_threshold=alert_summary.blocked_failure_threshold,
            network_failure_threshold=alert_summary.network_failure_threshold,
            cooldown_until=safety_state.get("cooldown_until"),
            cooldown_remaining_seconds=safety_state.get("cooldown_remaining_seconds"),
            safety_counters=safety_state.get("counters", {}),
        )
    elif pre_apply_state.get("cooldown_active") and not safety_state.get("cooldown_active"):
        structured_log(
            logger,
            "info",
            "ingestion.cooldown_cleared",
            user_id=user_id,
            crawl_run_id=int(run.id),
            reason=pre_apply_state.get("cooldown_reason"),
            cooldown_until=pre_apply_state.get("cooldown_until"),
        )


def finalize_run_record(
    *,
    run: CrawlRun,
    scholars: list[ScholarProfile],
    progress: RunProgress,
    failure_summary: RunFailureSummary,
    alert_summary: RunAlertSummary,
    idempotency_key: str | None,
    run_status: RunStatus,
) -> None:
    run.end_dt = datetime.now(UTC)
    if run.status != RunStatus.CANCELED:
        run.status = run_status
    run.error_log = {
        "scholar_results": progress.scholar_results,
        "summary": {
            "succeeded_count": progress.succeeded_count,
            "failed_count": progress.failed_count,
            "partial_count": progress.partial_count,
            "failed_state_counts": failure_summary.failed_state_counts,
            "failed_reason_counts": failure_summary.failed_reason_counts,
            "scrape_failure_counts": failure_summary.scrape_failure_counts,
            "retry_counts": {
                "retries_scheduled_count": failure_summary.retries_scheduled_count,
                "scholars_with_retries_count": failure_summary.scholars_with_retries_count,
                "retry_exhausted_count": failure_summary.retry_exhausted_count,
            },
            "alert_thresholds": {
                "blocked_failure_threshold": alert_summary.blocked_failure_threshold,
                "network_failure_threshold": alert_summary.network_failure_threshold,
                "retry_scheduled_threshold": alert_summary.retry_scheduled_threshold,
            },
            "alert_flags": alert_summary.alert_flags,
        },
        "meta": {"idempotency_key": idempotency_key} if idempotency_key else {},
    }


def resolve_run_status(
    *,
    scholar_count: int,
    succeeded_count: int,
    failed_count: int,
    partial_count: int,
) -> RunStatus:
    if scholar_count == 0:
        return RunStatus.SUCCESS
    if failed_count == scholar_count:
        return RunStatus.FAILED
    if failed_count > 0 or partial_count > 0:
        return RunStatus.PARTIAL_FAILURE
    if succeeded_count > 0:
        return RunStatus.SUCCESS
    return RunStatus.FAILED


def build_failure_debug_context(
    *,
    fetch_result: FetchResult,
    parsed_page: ParsedProfilePage,
    attempt_log: list[dict[str, Any]],
    page_logs: list[dict[str, Any]] | None = None,
    exception: Exception | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "requested_url": fetch_result.requested_url,
        "final_url": fetch_result.final_url,
        "status_code": fetch_result.status_code,
        "fetch_error": fetch_result.error,
        "state_reason": parsed_page.state_reason,
        "profile_name": parsed_page.profile_name,
        "profile_image_url": parsed_page.profile_image_url,
        "articles_range": parsed_page.articles_range,
        "has_show_more_button": parsed_page.has_show_more_button,
        "has_operation_error_banner": parsed_page.has_operation_error_banner,
        "warning_codes": parsed_page.warnings,
        "marker_counts_nonzero": {key: value for key, value in parsed_page.marker_counts.items() if value > 0},
        "body_length": len(fetch_result.body),
        "body_sha256": hashlib.sha256(fetch_result.body.encode("utf-8")).hexdigest() if fetch_result.body else None,
        "body_excerpt": _build_body_excerpt(fetch_result.body),
        "attempt_log": attempt_log,
    }
    if page_logs:
        context["page_logs"] = page_logs
    if exception is not None:
        context["exception_type"] = type(exception).__name__
        context["exception_message"] = str(exception)
    return context


def _log_alert_threshold_warnings(
    *,
    user_id: int,
    run: CrawlRun,
    failure_summary: RunFailureSummary,
    alert_summary: RunAlertSummary,
) -> None:
    if alert_summary.alert_flags["blocked_failure_threshold_exceeded"]:
        structured_log(
            logger,
            "warning",
            "ingestion.alert_blocked_failure_threshold_exceeded",
            user_id=user_id,
            crawl_run_id=int(run.id),
            blocked_failure_count=alert_summary.blocked_failure_count,
            threshold=alert_summary.blocked_failure_threshold,
        )
    if alert_summary.alert_flags["network_failure_threshold_exceeded"]:
        structured_log(
            logger,
            "warning",
            "ingestion.alert_network_failure_threshold_exceeded",
            user_id=user_id,
            crawl_run_id=int(run.id),
            network_failure_count=alert_summary.network_failure_count,
            threshold=alert_summary.network_failure_threshold,
        )
    if alert_summary.alert_flags["retry_scheduled_threshold_exceeded"]:
        structured_log(
            logger,
            "warning",
            "ingestion.alert_retry_scheduled_threshold_exceeded",
            user_id=user_id,
            crawl_run_id=int(run.id),
            retries_scheduled_count=failure_summary.retries_scheduled_count,
            threshold=alert_summary.retry_scheduled_threshold,
        )


def complete_run_for_user(
    *,
    user_settings: Any,
    run: CrawlRun,
    scholars: list[ScholarProfile],
    user_id: int,
    progress: RunProgress,
    idempotency_key: str | None,
    alert_blocked_failure_threshold: int,
    alert_network_failure_threshold: int,
    alert_retry_scheduled_threshold: int,
) -> tuple[RunFailureSummary, RunAlertSummary]:
    failure_summary = summarize_failures(scholar_results=progress.scholar_results)
    alert_summary = build_alert_summary(
        failure_summary=failure_summary,
        alert_blocked_failure_threshold=alert_blocked_failure_threshold,
        alert_network_failure_threshold=alert_network_failure_threshold,
        alert_retry_scheduled_threshold=alert_retry_scheduled_threshold,
    )
    _log_alert_threshold_warnings(
        user_id=user_id, run=run, failure_summary=failure_summary, alert_summary=alert_summary
    )
    apply_safety_outcome(user_settings=user_settings, run=run, user_id=user_id, alert_summary=alert_summary)
    run_status = resolve_run_status(
        scholar_count=len(scholars),
        succeeded_count=progress.succeeded_count,
        failed_count=progress.failed_count,
        partial_count=progress.partial_count,
    )
    finalize_run_record(
        run=run,
        scholars=scholars,
        progress=progress,
        failure_summary=failure_summary,
        alert_summary=alert_summary,
        idempotency_key=idempotency_key,
        run_status=run_status,
    )
    return failure_summary, alert_summary


def result_counters(result_entry: dict[str, Any]) -> tuple[int, int, int]:
    outcome = str(result_entry.get("outcome", "")).strip().lower()
    if outcome == "success":
        return 1, 0, 0
    if outcome == "partial":
        return 1, 0, 1
    if outcome == "failed":
        return 0, 1, 0
    raise RuntimeError(f"Unexpected scholar outcome label: {outcome!r}")


def find_scholar_result_index(
    *,
    scholar_results: list[dict[str, Any]],
    scholar_profile_id: int,
) -> int | None:
    for index, result_entry in enumerate(scholar_results):
        current_scholar_id = int_or_default(result_entry.get("scholar_profile_id"), 0)
        if current_scholar_id == scholar_profile_id:
            return index
    return None


def adjust_progress_counts(
    *,
    progress: RunProgress,
    succeeded_delta: int,
    failed_delta: int,
    partial_delta: int,
) -> None:
    progress.succeeded_count += succeeded_delta
    progress.failed_count += failed_delta
    progress.partial_count += partial_delta
    if progress.succeeded_count < 0 or progress.failed_count < 0 or progress.partial_count < 0:
        raise RuntimeError("RunProgress counters entered invalid negative state.")


def apply_outcome_to_progress(
    *,
    progress: RunProgress,
    outcome: ScholarProcessingOutcome,
) -> None:
    scholar_profile_id = int_or_default(outcome.result_entry.get("scholar_profile_id"), 0)
    if scholar_profile_id <= 0:
        raise RuntimeError("Scholar outcome missing valid scholar_profile_id.")
    prior_index = find_scholar_result_index(
        scholar_results=progress.scholar_results,
        scholar_profile_id=scholar_profile_id,
    )
    next_succeeded, next_failed, next_partial = result_counters(outcome.result_entry)
    if prior_index is None:
        progress.scholar_results.append(outcome.result_entry)
        adjust_progress_counts(
            progress=progress,
            succeeded_delta=next_succeeded,
            failed_delta=next_failed,
            partial_delta=next_partial,
        )
        return
    previous_entry = progress.scholar_results[prior_index]
    prev_succeeded, prev_failed, prev_partial = result_counters(previous_entry)
    progress.scholar_results[prior_index] = outcome.result_entry
    adjust_progress_counts(
        progress=progress,
        succeeded_delta=next_succeeded - prev_succeeded,
        failed_delta=next_failed - prev_failed,
        partial_delta=next_partial - prev_partial,
    )


def run_execution_summary(
    *,
    run: CrawlRun,
    scholars: list[ScholarProfile],
    progress: RunProgress,
) -> RunExecutionSummary:
    return RunExecutionSummary(
        crawl_run_id=run.id,
        status=run.status,
        scholar_count=len(scholars),
        succeeded_count=progress.succeeded_count,
        failed_count=progress.failed_count,
        partial_count=progress.partial_count,
        new_publication_count=run.new_pub_count,
    )


def log_run_completed(
    *,
    run: CrawlRun,
    user_id: int,
    scholars: list[ScholarProfile],
    progress: RunProgress,
    failure_summary: RunFailureSummary,
    alert_summary: RunAlertSummary,
) -> None:
    structured_log(
        logger,
        "info",
        "ingestion.run_completed",
        user_id=user_id,
        crawl_run_id=run.id,
        status=run.status.value,
        scholar_count=len(scholars),
        succeeded_count=progress.succeeded_count,
        failed_count=progress.failed_count,
        partial_count=progress.partial_count,
        new_publication_count=run.new_pub_count,
        blocked_failure_count=alert_summary.blocked_failure_count,
        network_failure_count=alert_summary.network_failure_count,
        retries_scheduled_count=failure_summary.retries_scheduled_count,
        alert_flags=alert_summary.alert_flags,
    )
