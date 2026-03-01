from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.common import ApiMeta
from app.api.schemas.publications import DisplayIdentifierData


class AdminUserData(BaseModel):
    id: int
    email: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class AdminUsersListData(BaseModel):
    users: list[AdminUserData]

    model_config = ConfigDict(extra="forbid")


class AdminUsersListEnvelope(BaseModel):
    data: AdminUsersListData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class AdminUserCreateRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    is_admin: bool = False

    model_config = ConfigDict(extra="forbid")


class AdminUserActiveUpdateRequest(BaseModel):
    is_active: bool

    model_config = ConfigDict(extra="forbid")


class AdminUserEnvelope(BaseModel):
    data: AdminUserData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(max_length=128)

    model_config = ConfigDict(extra="forbid")


class AdminScholarHttpSettingsData(BaseModel):
    user_agent: str
    rotate_user_agent: bool
    accept_language: str
    cookie: str

    model_config = ConfigDict(extra="forbid")


class AdminScholarHttpSettingsEnvelope(BaseModel):
    data: AdminScholarHttpSettingsData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class AdminScholarHttpSettingsUpdateRequest(BaseModel):
    user_agent: str
    rotate_user_agent: bool
    accept_language: str
    cookie: str

    model_config = ConfigDict(extra="forbid")


class AdminDbIntegrityCheckData(BaseModel):
    name: str
    count: int
    severity: str
    message: str

    model_config = ConfigDict(extra="forbid")


class AdminDbIntegrityData(BaseModel):
    status: str
    checked_at: datetime
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checks: list[AdminDbIntegrityCheckData] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class AdminDbIntegrityEnvelope(BaseModel):
    data: AdminDbIntegrityData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class AdminDbRepairJobData(BaseModel):
    id: int
    job_name: str
    requested_by: str | None
    dry_run: bool
    status: str
    scope: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    error_text: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class AdminDbRepairJobsData(BaseModel):
    jobs: list[AdminDbRepairJobData] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class AdminDbRepairJobsEnvelope(BaseModel):
    data: AdminDbRepairJobsData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class AdminPdfQueueItemData(BaseModel):
    publication_id: int
    title: str
    display_identifier: DisplayIdentifierData | None = None
    pdf_url: str | None
    status: str
    attempt_count: int
    last_failure_reason: str | None
    last_failure_detail: str | None
    last_source: str | None
    requested_by_user_id: int | None
    requested_by_email: str | None
    queued_at: datetime | None
    last_attempt_at: datetime | None
    resolved_at: datetime | None
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")


class AdminPdfQueueData(BaseModel):
    items: list[AdminPdfQueueItemData] = Field(default_factory=list)
    total_count: int = 0
    page: int = 1
    page_size: int = 100
    has_next: bool = False
    has_prev: bool = False

    model_config = ConfigDict(extra="forbid")


class AdminPdfQueueEnvelope(BaseModel):
    data: AdminPdfQueueData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class AdminPdfQueueRequeueData(BaseModel):
    publication_id: int
    queued: bool
    status: str
    message: str

    model_config = ConfigDict(extra="forbid")


class AdminPdfQueueRequeueEnvelope(BaseModel):
    data: AdminPdfQueueRequeueData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class AdminPdfQueueBulkEnqueueData(BaseModel):
    requested_count: int
    queued_count: int
    message: str

    model_config = ConfigDict(extra="forbid")


class AdminPdfQueueBulkEnqueueEnvelope(BaseModel):
    data: AdminPdfQueueBulkEnqueueData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class AdminRepairPublicationLinksRequest(BaseModel):
    scope_mode: Literal["single_user", "all_users"] = "single_user"
    user_id: int | None = Field(default=None, ge=1)
    scholar_profile_ids: list[int] = Field(default_factory=list, max_length=200)
    dry_run: bool = True
    gc_orphan_publications: bool = False
    requested_by: str | None = None
    confirmation_text: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_scope(self) -> AdminRepairPublicationLinksRequest:
        if self.scope_mode == "single_user" and self.user_id is None:
            raise ValueError("user_id is required when scope_mode=single_user.")
        if self.scope_mode == "all_users" and self.user_id is not None:
            raise ValueError("user_id must be omitted when scope_mode=all_users.")
        if not self.dry_run and self.scope_mode == "all_users":
            expected = "REPAIR ALL USERS"
            provided = (self.confirmation_text or "").strip()
            if provided != expected:
                raise ValueError("confirmation_text must equal 'REPAIR ALL USERS' when applying a repair to all users.")
        return self


class AdminRepairPublicationLinksResultData(BaseModel):
    job_id: int
    status: str
    scope: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class AdminRepairPublicationLinksEnvelope(BaseModel):
    data: AdminRepairPublicationLinksResultData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class AdminNearDuplicateClusterMemberData(BaseModel):
    publication_id: int
    title: str
    year: int | None
    citation_count: int

    model_config = ConfigDict(extra="forbid")


class AdminNearDuplicateClusterData(BaseModel):
    cluster_key: str
    winner_publication_id: int
    member_count: int
    similarity_score: float = Field(ge=0.0, le=1.0)
    members: list[AdminNearDuplicateClusterMemberData] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class AdminRepairPublicationNearDuplicatesRequest(BaseModel):
    dry_run: bool = True
    similarity_threshold: float = Field(default=0.78, ge=0.5, le=1.0)
    min_shared_tokens: int = Field(default=3, ge=1, le=8)
    max_year_delta: int = Field(default=1, ge=0, le=5)
    max_clusters: int = Field(default=25, ge=1, le=200)
    selected_cluster_keys: list[str] = Field(default_factory=list, max_length=200)
    requested_by: str | None = None
    confirmation_text: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_apply_mode(self) -> AdminRepairPublicationNearDuplicatesRequest:
        if self.dry_run:
            return self
        if not self.selected_cluster_keys:
            raise ValueError("selected_cluster_keys is required when dry_run=false.")
        expected = "MERGE SELECTED DUPLICATES"
        provided = (self.confirmation_text or "").strip()
        if provided != expected:
            raise ValueError(
                "confirmation_text must equal 'MERGE SELECTED DUPLICATES' when applying near-duplicate merges."
            )
        return self


class AdminRepairPublicationNearDuplicatesResultData(BaseModel):
    job_id: int
    status: str
    scope: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    clusters: list[AdminNearDuplicateClusterData] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class AdminRepairPublicationNearDuplicatesEnvelope(BaseModel):
    data: AdminRepairPublicationNearDuplicatesResultData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")
