from __future__ import annotations

from fastapi import Depends

from app.services.domains.ingestion import application as ingestion_service
from app.services.domains.scholar import source as scholar_source_service


def get_scholar_source() -> scholar_source_service.ScholarSource:
    return scholar_source_service.LiveScholarSource()


def get_ingestion_service(
    source: scholar_source_service.ScholarSource = Depends(get_scholar_source),
) -> ingestion_service.ScholarIngestionService:
    return ingestion_service.ScholarIngestionService(source=source)
