from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_current_user
from app.api.errors import ApiException
from app.api.responses import success_payload
from app.api.schemas import (
    MessageEnvelope,
    ScholarCreateRequest,
    ScholarEnvelope,
    ScholarsListEnvelope,
)
from app.db.models import User
from app.db.session import get_db_session
from app.services import scholars as scholar_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scholars", tags=["api-scholars"])


def _serialize_scholar(profile) -> dict[str, object]:
    return {
        "id": int(profile.id),
        "scholar_id": profile.scholar_id,
        "display_name": profile.display_name,
        "is_enabled": bool(profile.is_enabled),
        "baseline_completed": bool(profile.baseline_completed),
        "last_run_dt": profile.last_run_dt,
        "last_run_status": (
            profile.last_run_status.value if profile.last_run_status is not None else None
        ),
    }


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
            "scholars": [_serialize_scholar(profile) for profile in scholars],
        },
    )


@router.post(
    "",
    response_model=ScholarEnvelope,
    status_code=201,
)
async def create_scholar(
    payload: ScholarCreateRequest,
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_api_current_user),
):
    try:
        created = await scholar_service.create_scholar_for_user(
            db_session,
            user_id=current_user.id,
            scholar_id=payload.scholar_id,
            display_name=payload.display_name or "",
        )
    except scholar_service.ScholarServiceError as exc:
        raise ApiException(
            status_code=400,
            code="invalid_scholar",
            message=str(exc),
        ) from exc
    logger.info(
        "api.scholars.created",
        extra={
            "event": "api.scholars.created",
            "user_id": current_user.id,
            "scholar_profile_id": created.id,
        },
    )
    return success_payload(
        request,
        data=_serialize_scholar(created),
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
    logger.info(
        "api.scholars.toggled",
        extra={
            "event": "api.scholars.toggled",
            "user_id": current_user.id,
            "scholar_profile_id": updated.id,
            "is_enabled": updated.is_enabled,
        },
    )
    return success_payload(
        request,
        data=_serialize_scholar(updated),
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
    await scholar_service.delete_scholar(db_session, profile=profile)
    logger.info(
        "api.scholars.deleted",
        extra={
            "event": "api.scholars.deleted",
            "user_id": current_user.id,
            "scholar_profile_id": scholar_profile_id,
        },
    )
    return success_payload(
        request,
        data={"message": "Scholar deleted."},
    )
