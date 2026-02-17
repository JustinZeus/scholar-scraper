from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.session import check_database

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    if await check_database():
        return {"status": "ok"}
    raise HTTPException(status_code=500, detail="database unavailable")

