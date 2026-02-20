from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.db.models import RunStatus
from app.services.domains.scholar.parser import ParsedProfilePage, PublicationCandidate
from app.services.domains.scholar.source import FetchResult


@dataclass(frozen=True)
class RunExecutionSummary:
    crawl_run_id: int
    status: RunStatus
    scholar_count: int
    succeeded_count: int
    failed_count: int
    partial_count: int
    new_publication_count: int


@dataclass(frozen=True)
class PagedParseResult:
    fetch_result: FetchResult
    parsed_page: ParsedProfilePage
    first_page_fetch_result: FetchResult
    first_page_parsed_page: ParsedProfilePage
    first_page_fingerprint_sha256: str | None
    publications: list[PublicationCandidate]
    attempt_log: list[dict[str, Any]]
    page_logs: list[dict[str, Any]]
    pages_fetched: int
    pages_attempted: int
    has_more_remaining: bool
    pagination_truncated_reason: str | None
    continuation_cstart: int | None
    skipped_no_change: bool


@dataclass
class RunProgress:
    succeeded_count: int = 0
    failed_count: int = 0
    partial_count: int = 0
    scholar_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ScholarProcessingOutcome:
    result_entry: dict[str, Any]
    succeeded_count_delta: int
    failed_count_delta: int
    partial_count_delta: int
    discovered_publication_count: int


@dataclass(frozen=True)
class RunFailureSummary:
    failed_state_counts: dict[str, int]
    failed_reason_counts: dict[str, int]
    scrape_failure_counts: dict[str, int]
    retries_scheduled_count: int
    scholars_with_retries_count: int
    retry_exhausted_count: int


@dataclass(frozen=True)
class RunAlertSummary:
    blocked_failure_count: int
    network_failure_count: int
    blocked_failure_threshold: int
    network_failure_threshold: int
    retry_scheduled_threshold: int
    alert_flags: dict[str, bool]


@dataclass
class PagedLoopState:
    fetch_result: FetchResult
    parsed_page: ParsedProfilePage
    attempt_log: list[dict[str, Any]]
    page_logs: list[dict[str, Any]]
    publications: list[PublicationCandidate]
    pages_fetched: int
    pages_attempted: int
    current_cstart: int
    next_cstart: int
    has_more_remaining: bool = False
    pagination_truncated_reason: str | None = None
    continuation_cstart: int | None = None


class RunAlreadyInProgressError(RuntimeError):
    """Raised when a run lock for a user is already held by another process."""


class RunBlockedBySafetyPolicyError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        safety_state: dict[str, Any],
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.safety_state = safety_state
