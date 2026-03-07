from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_current_user
from app.api.errors import ApiException
from app.api.responses import success_payload
from app.api.routers.scholar_helpers import (
    enqueue_initial_scrape_job_for_scholar,
    hydrate_scholar_metadata_if_needed,
    read_uploaded_image,
    require_user_profile,
    search_kwargs,
    search_response_data,
    serialize_scholar,
)
from app.api.runtime_deps import get_scholar_source
from app.api.schemas import (
    DataExportEnvelope,
    DataImportEnvelope,
    DataImportRequest,
    MessageEnvelope,
    ScholarBulkCountEnvelope,
    ScholarBulkIdsRequest,
    ScholarBulkToggleRequest,
    ScholarCreateRequest,
    ScholarEnvelope,
    ScholarImageUrlUpdateRequest,
    ScholarSearchEnvelope,
    ScholarsListEnvelope,
)
from app.db.models import User
from app.db.session import get_db_session
from app.logging_utils import structured_log
from app.services.portability import application as import_export_service
from app.services.scholar.source import ScholarSource
from app.services.scholars import application as scholar_service
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scholars", tags=["api-scholars"])


def _parse_ids_param(ids: str | None) -> list[int] | None:
    if not ids:
        return None
    parts = [p.strip() for p in ids.split(",") if p.strip()]
    if not parts:
        return None
    return [int(p) for p in parts]


@router.get(
    "",
    response_model=ScholarsListEnvelope,
)
async def list_scholars(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    scholars = await scholar_service.list_scholars_for_user(
        db_session,
        user_id=current_user.id,
    )
    return success_payload(
        request,
        data={
            "scholars": [serialize_scholar(profile) for profile in scholars],
        },
    )


@router.get(
    "/export",
    response_model=DataExportEnvelope,
)
async def export_scholars_and_publications(
    request: Request,
    ids: str | None = Query(None, description="Comma-separated scholar profile IDs to export"),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    scholar_profile_ids = _parse_ids_param(ids)
    data = await import_export_service.export_user_data(
        db_session,
        user_id=current_user.id,
        scholar_profile_ids=scholar_profile_ids,
    )
    return success_payload(request, data=data)


@router.post(
    "/bulk-delete",
    response_model=ScholarBulkCountEnvelope,
)
async def bulk_delete_scholars(
    payload: ScholarBulkIdsRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    deleted_count = await scholar_service.bulk_delete_scholars(
        db_session,
        user_id=current_user.id,
        scholar_profile_ids=payload.scholar_profile_ids,
        upload_dir=settings.scholar_image_upload_dir,
    )
    structured_log(
        logger,
        "info",
        "scholars.bulk_delete",
        user_id=current_user.id,
        requested_ids=payload.scholar_profile_ids,
        deleted_count=deleted_count,
    )
    return success_payload(request, data={"deleted_count": deleted_count, "updated_count": 0})


@router.post(
    "/bulk-toggle",
    response_model=ScholarBulkCountEnvelope,
)
async def bulk_toggle_scholars(
    payload: ScholarBulkToggleRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    updated_count = await scholar_service.bulk_toggle_scholars(
        db_session,
        user_id=current_user.id,
        scholar_profile_ids=payload.scholar_profile_ids,
        is_enabled=payload.is_enabled,
    )
    structured_log(
        logger,
        "info",
        "scholars.bulk_toggle",
        user_id=current_user.id,
        requested_ids=payload.scholar_profile_ids,
        is_enabled=payload.is_enabled,
        updated_count=updated_count,
    )
    return success_payload(request, data={"deleted_count": 0, "updated_count": updated_count})


@router.post(
    "/import",
    response_model=DataImportEnvelope,
)
async def import_scholars_and_publications(
    payload: DataImportRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    if (
        payload.schema_version is not None
        and int(payload.schema_version) != import_export_service.EXPORT_SCHEMA_VERSION
    ):
        raise ApiException(
            status_code=400,
            code="invalid_import_schema_version",
            message=(
                f"Import schema version is not supported. Expected {import_export_service.EXPORT_SCHEMA_VERSION}."
            ),
        )
    try:
        result = await import_export_service.import_user_data(
            db_session,
            user_id=current_user.id,
            scholars=[item.model_dump() for item in payload.scholars],
            publications=[item.model_dump() for item in payload.publications],
        )
    except import_export_service.ImportExportError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_import_payload",
            message=str(exc),
        ) from exc
    structured_log(logger, "info", "api.scholars.imported", user_id=current_user.id, **result)
    return success_payload(request, data=result)


@router.post(
    "",
    response_model=ScholarEnvelope,
    status_code=201,
)
async def create_scholar(
    payload: ScholarCreateRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    source: ScholarSource = Depends(get_scholar_source),
    current_user: User = Depends(get_api_current_user),
):
    try:
        created = await scholar_service.create_scholar_for_user(
            db_session,
            user_id=current_user.id,
            scholar_id=payload.scholar_id,
            display_name="",
            profile_image_url=payload.profile_image_url,
        )
    except scholar_service.ScholarServiceError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_scholar",
            message=str(exc),
        ) from exc
    structured_log(logger, "info", "api.scholars.created", user_id=current_user.id, scholar_profile_id=created.id)
    await enqueue_initial_scrape_job_for_scholar(
        db_session,
        profile=created,
        user_id=current_user.id,
    )
    created = await hydrate_scholar_metadata_if_needed(
        db_session,
        profile=created,
        source=source,
        user_id=current_user.id,
    )

    return success_payload(
        request,
        data=serialize_scholar(created),
    )


@router.get(
    "/search",
    response_model=ScholarSearchEnvelope,
)
async def search_scholars(
    request: Request,
    query: str = Query(..., min_length=2, max_length=120),
    limit: int = Query(10, ge=1, le=25),
    db_session: AsyncSession = Depends(get_db_session),
    source: ScholarSource = Depends(get_scholar_source),
    current_user: User = Depends(get_api_current_user),
):
    try:
        parsed = await scholar_service.search_author_candidates(
            source=source,
            db_session=db_session,
            query=query,
            limit=limit,
            **search_kwargs(),
        )
    except scholar_service.ScholarServiceError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_scholar_search",
            message=str(exc),
        ) from exc

    structured_log(
        logger,
        "info",
        "api.scholars.search.completed",
        user_id=current_user.id,
        query=query.strip(),
        candidate_count=len(parsed.candidates),
        state=parsed.state.value,
    )
    return success_payload(
        request,
        data=search_response_data(query, parsed),
    )


@router.patch(
    "/{scholar_profile_id}/toggle",
    response_model=ScholarEnvelope,
)
async def toggle_scholar(
    scholar_profile_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    profile = await scholar_service.get_user_scholar_by_id(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
    )
    if profile is None:
        raise ApiException(
            status_code=404,
            code="scholar_not_found",
            message="Scholar not found.",
        )
    updated = await scholar_service.toggle_scholar_enabled(db_session, profile=profile)
    structured_log(
        logger,
        "info",
        "api.scholars.toggled",
        user_id=current_user.id,
        scholar_profile_id=updated.id,
        is_enabled=updated.is_enabled,
    )
    return success_payload(
        request,
        data=serialize_scholar(updated),
    )


@router.delete(
    "/{scholar_profile_id}",
    response_model=MessageEnvelope,
)
async def delete_scholar(
    scholar_profile_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    profile = await scholar_service.get_user_scholar_by_id(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
    )
    if profile is None:
        raise ApiException(
            status_code=404,
            code="scholar_not_found",
            message="Scholar not found.",
        )
    await scholar_service.delete_scholar(
        db_session,
        profile=profile,
        upload_dir=settings.scholar_image_upload_dir,
    )
    structured_log(
        logger, "info", "api.scholars.deleted", user_id=current_user.id, scholar_profile_id=scholar_profile_id
    )
    return success_payload(
        request,
        data={"message": "Scholar deleted."},
    )


@router.put(
    "/{scholar_profile_id}/image/url",
    response_model=ScholarEnvelope,
)
async def update_scholar_image_url(
    scholar_profile_id: int,
    payload: ScholarImageUrlUpdateRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    profile = await scholar_service.get_user_scholar_by_id(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
    )
    if profile is None:
        raise ApiException(
            status_code=404,
            code="scholar_not_found",
            message="Scholar not found.",
        )

    try:
        updated = await scholar_service.set_profile_image_override_url(
            db_session,
            profile=profile,
            image_url=payload.image_url,
            upload_dir=settings.scholar_image_upload_dir,
        )
    except scholar_service.ScholarServiceError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_scholar_image",
            message=str(exc),
        ) from exc

    structured_log(
        logger, "info", "api.scholars.image_url_updated", user_id=current_user.id, scholar_profile_id=updated.id
    )
    return success_payload(
        request,
        data=serialize_scholar(updated),
    )


@router.post(
    "/{scholar_profile_id}/image/upload",
    response_model=ScholarEnvelope,
)
async def upload_scholar_image(
    scholar_profile_id: int,
    request: Request,
    image: UploadFile = File(...),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    profile = await require_user_profile(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
    )

    image_bytes = await read_uploaded_image(image)
    try:
        updated = await scholar_service.set_profile_image_upload(
            db_session,
            profile=profile,
            content_type=image.content_type,
            image_bytes=image_bytes,
            upload_dir=settings.scholar_image_upload_dir,
            max_upload_bytes=settings.scholar_image_upload_max_bytes,
        )
    except scholar_service.ScholarServiceError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_scholar_image",
            message=str(exc),
        ) from exc

    image_size = len(image_bytes)
    structured_log(
        logger,
        "info",
        "api.scholars.image_uploaded",
        user_id=current_user.id,
        scholar_profile_id=updated.id,
        content_type=image.content_type,
        size_bytes=image_size,
    )
    return success_payload(
        request,
        data=serialize_scholar(updated),
    )


@router.delete(
    "/{scholar_profile_id}/image",
    response_model=ScholarEnvelope,
)
async def clear_scholar_image_customization(
    scholar_profile_id: int,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    profile = await scholar_service.get_user_scholar_by_id(
        db_session,
        user_id=current_user.id,
        scholar_profile_id=scholar_profile_id,
    )
    if profile is None:
        raise ApiException(
            status_code=404,
            code="scholar_not_found",
            message="Scholar not found.",
        )

    updated = await scholar_service.clear_profile_image_customization(
        db_session,
        profile=profile,
        upload_dir=settings.scholar_image_upload_dir,
    )
    structured_log(logger, "info", "api.scholars.image_cleared", user_id=current_user.id, scholar_profile_id=updated.id)
    return success_payload(
        request,
        data=serialize_scholar(updated),
    )
