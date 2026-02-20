from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Publication
from app.services.domains.portability.constants import (
    EXPORT_SCHEMA_VERSION,
    MAX_IMPORT_PUBLICATIONS,
    MAX_IMPORT_SCHOLARS,
)
from app.services.domains.portability.exporting import export_user_data
from app.services.domains.portability.normalize import _validate_import_sizes
from app.services.domains.portability.publication_import import (
    _build_imported_publication_input,
    _initialize_import_counters,
    _upsert_imported_publication,
)
from app.services.domains.portability.scholar_import import _upsert_imported_scholars
from app.services.domains.portability.types import ImportExportError, ImportedPublicationInput


async def import_user_data(
    db_session: AsyncSession,
    *,
    user_id: int,
    scholars: list[dict[str, Any]],
    publications: list[dict[str, Any]],
) -> dict[str, int]:
    _validate_import_sizes(scholars=scholars, publications=publications)
    scholar_map, counters = await _upsert_imported_scholars(
        db_session,
        user_id=user_id,
        scholars=scholars,
    )
    cluster_cache: dict[str, Publication | None] = {}
    fingerprint_cache: dict[str, Publication | None] = {}
    _initialize_import_counters(counters)
    for item in publications:
        parsed_item = _build_imported_publication_input(
            item=item,
            scholar_map=scholar_map,
        )
        if parsed_item is None:
            counters["skipped_records"] += 1
            continue
        await _upsert_imported_publication(
            db_session,
            payload=parsed_item,
            cluster_cache=cluster_cache,
            fingerprint_cache=fingerprint_cache,
            counters=counters,
        )
    await db_session.commit()
    return counters


__all__ = [
    "EXPORT_SCHEMA_VERSION",
    "MAX_IMPORT_SCHOLARS",
    "MAX_IMPORT_PUBLICATIONS",
    "ImportExportError",
    "ImportedPublicationInput",
    "export_user_data",
    "import_user_data",
]
