from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_current_user
from app.api.errors import ApiException
from app.db.models import User
from app.db.session import get_db_session
from app.services.domains.scholars import application as scholar_service
from app.settings import settings

router = APIRouter(tags=["media"])


@router.get("/scholar-images/{scholar_profile_id}/upload")
async def get_uploaded_scholar_image(
    scholar_profile_id: int,
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
    if not profile.profile_image_upload_path:
        raise ApiException(
            status_code=404,
            code="scholar_image_not_found",
            message="Scholar image not found.",
        )

    try:
        image_path = scholar_service.resolve_upload_file_path(
            upload_dir=settings.scholar_image_upload_dir,
            relative_path=profile.profile_image_upload_path,
        )
    except scholar_service.ScholarServiceError as exc:
        raise ApiException(
            status_code=404,
            code="scholar_image_not_found",
            message="Scholar image not found.",
        ) from exc

    if not image_path.exists() or not image_path.is_file():
        raise ApiException(
            status_code=404,
            code="scholar_image_not_found",
            message="Scholar image not found.",
        )

    media_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    return FileResponse(path=image_path, media_type=media_type)
