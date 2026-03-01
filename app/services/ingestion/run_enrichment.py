from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CrawlRun, RunStatus
from app.logging_utils import structured_log
from app.services.ingestion.enrichment import EnrichmentRunner

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[Any]] = set()


async def background_enrich(
    session_factory: Any,
    enrichment_runner: EnrichmentRunner,
    *,
    run_id: int,
    intended_final_status: RunStatus,
    openalex_api_key: str | None = None,
) -> None:
    try:
        async with session_factory() as session:
            await enrichment_runner.enrich_pending_publications(
                session,
                run_id=run_id,
                openalex_api_key=openalex_api_key,
            )
            run = await session.get(CrawlRun, run_id)
            if run is not None and run.status == RunStatus.RESOLVING:
                run.status = intended_final_status
            await session.commit()
            structured_log(
                logger,
                "info",
                "ingestion.background_enrichment_complete",
                run_id=run_id,
                final_status=str(intended_final_status),
            )
    except Exception:
        structured_log(
            logger,
            "exception",
            "ingestion.background_enrichment_failed",
            run_id=run_id,
        )
        try:
            async with session_factory() as fallback_session:
                run = await fallback_session.get(CrawlRun, run_id)
                if run is not None and run.status == RunStatus.RESOLVING:
                    run.status = intended_final_status
                await fallback_session.commit()
        except Exception:
            structured_log(
                logger,
                "exception",
                "ingestion.background_enrichment_fallback_failed",
                run_id=run_id,
            )


async def inline_enrich_and_finalize(
    db_session: AsyncSession,
    enrichment_runner: EnrichmentRunner,
    *,
    run: CrawlRun,
    user_settings: Any,
    intended_final_status: RunStatus,
) -> None:
    try:
        await enrichment_runner.enrich_pending_publications(
            db_session,
            run_id=run.id,
            openalex_api_key=getattr(user_settings, "openalex_api_key", None),
        )
    except Exception:
        structured_log(
            logger,
            "exception",
            "ingestion.enrichment_failed",
            run_id=run.id,
        )
    if run.status == RunStatus.RESOLVING:
        run.status = intended_final_status
    await db_session.commit()


def spawn_background_enrichment_task(
    session_factory: Any,
    enrichment_runner: EnrichmentRunner,
    *,
    run_id: int,
    intended_final_status: RunStatus,
    openalex_api_key: str | None,
) -> None:
    task = asyncio.create_task(
        background_enrich(
            session_factory,
            enrichment_runner,
            run_id=run_id,
            intended_final_status=intended_final_status,
            openalex_api_key=openalex_api_key,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
