from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.common import ApiMeta


class ScholarItemData(BaseModel):
    id: int
    scholar_id: str
    display_name: str | None
    profile_image_url: str | None
    profile_image_source: str
    is_enabled: bool
    baseline_completed: bool
    last_run_dt: datetime | None
    last_run_status: str | None

    model_config = ConfigDict(extra="forbid")


class ScholarsListData(BaseModel):
    scholars: list[ScholarItemData]

    model_config = ConfigDict(extra="forbid")


class ScholarsListEnvelope(BaseModel):
    data: ScholarsListData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class ScholarCreateRequest(BaseModel):
    scholar_id: str
    profile_image_url: str | None = None

    model_config = ConfigDict(extra="forbid")


class ScholarEnvelope(BaseModel):
    data: ScholarItemData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class ScholarSearchCandidateData(BaseModel):
    scholar_id: str
    display_name: str
    affiliation: str | None
    email_domain: str | None
    cited_by_count: int | None
    interests: list[str] = Field(default_factory=list)
    profile_url: str
    profile_image_url: str | None

    model_config = ConfigDict(extra="forbid")


class ScholarSearchData(BaseModel):
    query: str
    state: str
    state_reason: str
    action_hint: str | None = None
    candidates: list[ScholarSearchCandidateData]
    warnings: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ScholarSearchEnvelope(BaseModel):
    data: ScholarSearchData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class ScholarImageUrlUpdateRequest(BaseModel):
    image_url: str

    model_config = ConfigDict(extra="forbid")


class ScholarExportItemData(BaseModel):
    scholar_id: str
    display_name: str | None = None
    is_enabled: bool = True
    profile_image_override_url: str | None = None

    model_config = ConfigDict(extra="forbid")


class PublicationExportItemData(BaseModel):
    scholar_id: str
    cluster_id: str | None = None
    fingerprint_sha256: str | None = None
    title: str
    year: int | None = None
    citation_count: int = 0
    author_text: str | None = None
    venue_text: str | None = None
    pub_url: str | None = None
    pdf_url: str | None = None
    is_read: bool = False

    model_config = ConfigDict(extra="forbid")


class DataExportData(BaseModel):
    schema_version: int
    exported_at: str
    scholars: list[ScholarExportItemData]
    publications: list[PublicationExportItemData]

    model_config = ConfigDict(extra="forbid")


class DataExportEnvelope(BaseModel):
    data: DataExportData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class ScholarBulkIdsRequest(BaseModel):
    scholar_profile_ids: list[int] = Field(..., min_length=1, max_length=500)

    model_config = ConfigDict(extra="forbid")


class ScholarBulkToggleRequest(BaseModel):
    scholar_profile_ids: list[int] = Field(..., min_length=1, max_length=500)
    is_enabled: bool

    model_config = ConfigDict(extra="forbid")


class ScholarBulkCountData(BaseModel):
    deleted_count: int = 0
    updated_count: int = 0

    model_config = ConfigDict(extra="forbid")


class ScholarBulkCountEnvelope(BaseModel):
    data: ScholarBulkCountData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class DataImportRequest(BaseModel):
    schema_version: int | None = None
    exported_at: str | None = None
    scholars: list[ScholarExportItemData] = Field(default_factory=list)
    publications: list[PublicationExportItemData] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def unwrap_export_envelope(cls, values: dict) -> dict:
        """Accept the full export envelope format (with data/meta wrapper)."""
        if isinstance(values, dict) and "data" in values and isinstance(values["data"], dict):
            return values["data"]
        return values


class DataImportResultData(BaseModel):
    scholars_created: int
    scholars_updated: int
    publications_created: int
    publications_updated: int
    links_created: int
    links_updated: int
    skipped_records: int

    model_config = ConfigDict(extra="forbid")


class DataImportEnvelope(BaseModel):
    data: DataImportResultData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")
