from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import admin, admin_dbops, auth, publications, runs, scholars, settings

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(admin.router)
router.include_router(admin_dbops.router)
router.include_router(scholars.router)
router.include_router(settings.router)
router.include_router(runs.router)
router.include_router(publications.router)
