from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.domains.publications.pdf_queue import (
    enqueue_missing_pdf_jobs,
    enqueue_retry_pdf_job,
    overlay_pdf_job_state,
)
from app.services.domains.publications.types import PublicationListItem

logger = logging.getLogger(__name__)


async def schedule_missing_pdf_enrichment_for_user(
    db_session: AsyncSession,
    *,
    user_id: int,
    request_email: str | None,
    items: list[PublicationListItem],
    max_items: int,
) -> int:
    queued_ids = await enqueue_missing_pdf_jobs(
        db_session,
        user_id=user_id,
        request_email=request_email,
        rows=items,
        max_items=max_items,
    )
    logger.info(
        "publications.enrichment.scheduled",
        extra={
            "event": "publications.enrichment.scheduled",
            "user_id": user_id,
            "publication_count": len(queued_ids),
        },
    )
    return len(queued_ids)


async def schedule_retry_pdf_enrichment_for_row(
    db_session: AsyncSession,
    *,
    user_id: int,
    request_email: str | None,
    item: PublicationListItem,
) -> bool:
    queued = await enqueue_retry_pdf_job(
        db_session,
        user_id=user_id,
        request_email=request_email,
        row=item,
    )
    logger.info(
        "publications.enrichment.retry_scheduled",
        extra={
            "event": "publications.enrichment.retry_scheduled",
            "user_id": user_id,
            "publication_id": item.publication_id,
            "queued": queued,
        },
    )
    return queued


async def hydrate_pdf_enrichment_state(
    db_session: AsyncSession,
    *,
    items: list[PublicationListItem],
) -> list[PublicationListItem]:
    return await overlay_pdf_job_state(db_session, rows=items)
