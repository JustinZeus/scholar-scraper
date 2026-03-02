from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from app.db.models import Publication, PublicationPdfJob
from app.db.session import get_session_factory
from app.logging_utils import structured_log
from app.services.publication_identifiers import application as identifier_service
from app.services.publications.pdf_queue_common import (
    PDF_STATUS_FAILED,
    PDF_STATUS_RESOLVED,
    PDF_STATUS_RUNNING,
    event_row,
    queued_job,
    utcnow,
)
from app.services.publications.pdf_resolution_pipeline import (
    resolve_publication_pdf_outcome_for_row,
)
from app.services.publications.types import PublicationListItem
from app.services.unpaywall.application import (
    FAILURE_RESOLUTION_EXCEPTION,
    OaResolutionOutcome,
)
from app.settings import settings

PDF_EVENT_ATTEMPT_STARTED = "attempt_started"
PDF_EVENT_RESOLVED = "resolved"
PDF_EVENT_FAILED = "failed"

_BUDGET_COOLDOWN_MINUTES = 15

logger = logging.getLogger(__name__)
_scheduled_tasks: set[asyncio.Task[None]] = set()
_budget_cooldown_until: datetime | None = None


def is_budget_cooldown_active() -> bool:
    return _budget_cooldown_until is not None and datetime.now(UTC) < _budget_cooldown_until


def _enter_budget_cooldown() -> None:
    global _budget_cooldown_until
    _budget_cooldown_until = datetime.now(UTC) + timedelta(minutes=_BUDGET_COOLDOWN_MINUTES)


async def _mark_attempt_started(
    *,
    publication_id: int,
    user_id: int,
) -> None:
    session_factory = get_session_factory()
    async with session_factory() as db_session:
        job = await db_session.get(PublicationPdfJob, publication_id)
        if job is None:
            job = queued_job(publication_id=publication_id, user_id=user_id)
            db_session.add(job)
        job.status = PDF_STATUS_RUNNING
        job.last_attempt_at = utcnow()
        job.attempt_count = int(job.attempt_count or 0) + 1
        db_session.add(
            event_row(
                publication_id=publication_id,
                user_id=user_id,
                event_type=PDF_EVENT_ATTEMPT_STARTED,
                status=PDF_STATUS_RUNNING,
            )
        )
        await db_session.commit()


def _failed_outcome(
    *,
    row: PublicationListItem,
) -> OaResolutionOutcome:
    return OaResolutionOutcome(
        publication_id=row.publication_id,
        doi=None,
        pdf_url=None,
        failure_reason=FAILURE_RESOLUTION_EXCEPTION,
        source=None,
        used_crossref=False,
    )


async def _fetch_outcome_for_row(
    *,
    row: PublicationListItem,
    request_email: str | None,
    openalex_api_key: str | None = None,
    allow_arxiv_lookup: bool = True,
) -> tuple[OaResolutionOutcome, bool]:
    pipeline_result = await resolve_publication_pdf_outcome_for_row(
        row=row,
        request_email=request_email,
        openalex_api_key=openalex_api_key,
        allow_arxiv_lookup=allow_arxiv_lookup,
    )
    outcome = pipeline_result.outcome
    if outcome is not None:
        return outcome, bool(pipeline_result.arxiv_rate_limited)
    return _failed_outcome(row=row), bool(pipeline_result.arxiv_rate_limited)


def _apply_publication_update(
    publication: Publication,
    *,
    pdf_url: str | None,
) -> None:
    if pdf_url and publication.pdf_url != pdf_url:
        publication.pdf_url = pdf_url


def _apply_job_outcome(job: PublicationPdfJob, *, outcome: OaResolutionOutcome) -> None:
    job.last_source = outcome.source
    if outcome.pdf_url:
        job.status = PDF_STATUS_RESOLVED
        job.resolved_at = utcnow()
        job.last_failure_reason = None
        job.last_failure_detail = None
        return
    job.status = PDF_STATUS_FAILED
    job.last_failure_reason = outcome.failure_reason
    job.last_failure_detail = outcome.failure_reason


def _result_event(outcome: OaResolutionOutcome) -> tuple[str, str]:
    if outcome.pdf_url:
        return PDF_EVENT_RESOLVED, PDF_STATUS_RESOLVED
    return PDF_EVENT_FAILED, PDF_STATUS_FAILED


async def _persist_outcome(
    *,
    publication_id: int,
    user_id: int,
    outcome: OaResolutionOutcome,
) -> None:
    session_factory = get_session_factory()
    async with session_factory() as db_session:
        publication = await db_session.get(Publication, publication_id)
        job = await db_session.get(PublicationPdfJob, publication_id)
        if publication is None or job is None:
            return
        _apply_publication_update(publication, pdf_url=outcome.pdf_url)
        await identifier_service.sync_identifiers_for_publication_resolution(
            db_session,
            publication=publication,
            source=outcome.source,
        )
        _apply_job_outcome(job, outcome=outcome)
        event_type, status = _result_event(outcome)
        db_session.add(
            event_row(
                publication_id=publication_id,
                user_id=user_id,
                event_type=event_type,
                status=status,
                source=outcome.source,
                failure_reason=outcome.failure_reason,
                message=outcome.failure_reason,
            )
        )
        await db_session.commit()


async def _resolve_publication_row(
    *,
    user_id: int,
    request_email: str | None,
    row: PublicationListItem,
    openalex_api_key: str | None = None,
    allow_arxiv_lookup: bool = True,
) -> bool:
    from app.services.openalex.client import OpenAlexBudgetExhaustedError

    await _mark_attempt_started(publication_id=row.publication_id, user_id=user_id)
    try:
        outcome, arxiv_rate_limited = await _fetch_outcome_for_row(
            row=row,
            request_email=request_email,
            openalex_api_key=openalex_api_key,
            allow_arxiv_lookup=allow_arxiv_lookup,
        )
    except OpenAlexBudgetExhaustedError:
        await _persist_outcome(
            publication_id=row.publication_id,
            user_id=user_id,
            outcome=_failed_outcome(row=row),
        )
        raise
    except Exception as exc:  # pragma: no cover - defensive network boundary
        structured_log(
            logger,
            "warning",
            "publications.pdf_queue.resolve_failed",
            publication_id=row.publication_id,
            error=str(exc),
        )
        outcome = _failed_outcome(row=row)
        arxiv_rate_limited = False
    await _persist_outcome(
        publication_id=row.publication_id,
        user_id=user_id,
        outcome=outcome,
    )
    return bool(arxiv_rate_limited)


async def _run_resolution_task(
    *,
    user_id: int,
    request_email: str | None,
    rows: list[PublicationListItem],
) -> None:
    from app.services.openalex.client import OpenAlexBudgetExhaustedError
    from app.services.settings import application as user_settings_service

    openalex_api_key: str | None = None
    try:
        session_factory = get_session_factory()
        async with session_factory() as key_session:
            user_settings = await user_settings_service.get_or_create_settings(key_session, user_id=user_id)
            openalex_api_key = getattr(user_settings, "openalex_api_key", None) or settings.openalex_api_key
    except Exception:
        openalex_api_key = settings.openalex_api_key

    arxiv_lookup_allowed = True
    for row in rows:
        try:
            arxiv_rate_limited = await _resolve_publication_row(
                user_id=user_id,
                request_email=request_email,
                row=row,
                openalex_api_key=openalex_api_key,
                allow_arxiv_lookup=arxiv_lookup_allowed,
            )
            if arxiv_rate_limited and arxiv_lookup_allowed:
                arxiv_lookup_allowed = False
                structured_log(
                    logger,
                    "warning",
                    "pdf_queue.arxiv_batch_disabled",
                    detail="arXiv temporarily disabled for remaining batch after rate limit",
                )
        except OpenAlexBudgetExhaustedError:
            _enter_budget_cooldown()
            structured_log(
                logger,
                "warning",
                "pdf_queue.budget_exhausted",
                detail="Stopping PDF resolution batch — OpenAlex daily budget exhausted",
                cooldown_minutes=_BUDGET_COOLDOWN_MINUTES,
            )
            break
        except Exception:
            structured_log(
                logger,
                "exception",
                "pdf_queue.row_failed",
                publication_id=row.publication_id,
            )
            try:
                await _persist_outcome(
                    publication_id=row.publication_id,
                    user_id=user_id,
                    outcome=_failed_outcome(row=row),
                )
            except Exception:
                structured_log(
                    logger,
                    "exception",
                    "pdf_queue.row_fail_persist_error",
                    publication_id=row.publication_id,
                )


def _register_task(task: asyncio.Task[None]) -> None:
    _scheduled_tasks.add(task)


def _drop_finished_task(task: asyncio.Task[None]) -> None:
    _scheduled_tasks.discard(task)
    try:
        task.result()
    except Exception:
        structured_log(logger, "exception", "publications.pdf_queue.task_failed")


def schedule_rows(
    *,
    user_id: int,
    request_email: str | None,
    rows: list[PublicationListItem],
) -> None:
    if not rows:
        return
    task = asyncio.create_task(
        _run_resolution_task(
            user_id=user_id,
            request_email=request_email,
            rows=rows,
        )
    )
    _register_task(task)
    task.add_done_callback(_drop_finished_task)
