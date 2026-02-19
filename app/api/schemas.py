from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiMeta(BaseModel):
    request_id: str | None = None

    model_config = ConfigDict(extra="forbid")


class ApiErrorData(BaseModel):
    code: str
    message: str
    details: Any | None = None

    model_config = ConfigDict(extra="forbid")


class ApiErrorEnvelope(BaseModel):
    error: ApiErrorData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class MessageData(BaseModel):
    message: str

    model_config = ConfigDict(extra="forbid")


class MessageEnvelope(BaseModel):
    data: MessageData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class SessionUserData(BaseModel):
    id: int
    email: str
    is_admin: bool
    is_active: bool

    model_config = ConfigDict(extra="forbid")


class AuthMeData(BaseModel):
    authenticated: bool
    csrf_token: str
    user: SessionUserData

    model_config = ConfigDict(extra="forbid")


class AuthMeEnvelope(BaseModel):
    data: AuthMeData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class CsrfBootstrapData(BaseModel):
    csrf_token: str
    authenticated: bool

    model_config = ConfigDict(extra="forbid")


class CsrfBootstrapEnvelope(BaseModel):
    data: CsrfBootstrapData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class LoginRequest(BaseModel):
    email: str
    password: str

    model_config = ConfigDict(extra="forbid")


class LoginData(BaseModel):
    authenticated: bool
    csrf_token: str
    user: SessionUserData

    model_config = ConfigDict(extra="forbid")


class LoginEnvelope(BaseModel):
    data: LoginData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str

    model_config = ConfigDict(extra="forbid")


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


class RunListItemData(BaseModel):
    id: int
    trigger_type: str
    status: str
    start_dt: datetime
    end_dt: datetime | None
    scholar_count: int
    new_publication_count: int
    failed_count: int
    partial_count: int

    model_config = ConfigDict(extra="forbid")


class RunsListData(BaseModel):
    runs: list[RunListItemData]

    model_config = ConfigDict(extra="forbid")


class RunsListEnvelope(BaseModel):
    data: RunsListData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class RunSummaryData(BaseModel):
    succeeded_count: int
    failed_count: int
    partial_count: int
    failed_state_counts: dict[str, int] = Field(default_factory=dict)
    failed_reason_counts: dict[str, int] = Field(default_factory=dict)
    scrape_failure_counts: dict[str, int] = Field(default_factory=dict)
    retry_counts: dict[str, int] = Field(default_factory=dict)
    alert_thresholds: dict[str, int] = Field(default_factory=dict)
    alert_flags: dict[str, bool] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class RunAttemptLogData(BaseModel):
    attempt: int
    cstart: int
    state: str | None = None
    state_reason: str | None = None
    status_code: int | None = None
    fetch_error: str | None = None

    model_config = ConfigDict(extra="forbid")


class RunPageLogData(BaseModel):
    page: int
    cstart: int
    state: str
    state_reason: str | None = None
    status_code: int | None = None
    publication_count: int = 0
    attempt_count: int = 0
    has_show_more_button: bool = False
    articles_range: str | None = None
    warning_codes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class RunDebugData(BaseModel):
    status_code: int | None = None
    final_url: str | None = None
    fetch_error: str | None = None
    body_sha256: str | None = None
    body_length: int | None = None
    has_show_more_button: bool | None = None
    articles_range: str | None = None
    state_reason: str | None = None
    warning_codes: list[str] = Field(default_factory=list)
    marker_counts_nonzero: dict[str, int] = Field(default_factory=dict)
    page_logs: list[RunPageLogData] = Field(default_factory=list)
    attempt_log: list[RunAttemptLogData] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class RunScholarResultData(BaseModel):
    scholar_profile_id: int
    scholar_id: str
    state: str
    state_reason: str | None = None
    outcome: str
    attempt_count: int = 0
    publication_count: int = 0
    start_cstart: int = 0
    continuation_cstart: int | None = None
    continuation_enqueued: bool = False
    continuation_cleared: bool = False
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    debug: RunDebugData | None = None

    model_config = ConfigDict(extra="forbid")


class RunDetailData(BaseModel):
    run: RunListItemData
    summary: RunSummaryData
    scholar_results: list[RunScholarResultData]

    model_config = ConfigDict(extra="forbid")


class RunDetailEnvelope(BaseModel):
    data: RunDetailData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class ManualRunData(BaseModel):
    run_id: int
    status: str
    scholar_count: int
    succeeded_count: int
    failed_count: int
    partial_count: int
    new_publication_count: int
    reused_existing_run: bool
    idempotency_key: str | None = None

    model_config = ConfigDict(extra="forbid")


class ManualRunEnvelope(BaseModel):
    data: ManualRunData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class QueueItemData(BaseModel):
    id: int
    scholar_profile_id: int
    scholar_label: str
    status: str
    reason: str
    dropped_reason: str | None
    attempt_count: int
    resume_cstart: int
    next_attempt_dt: datetime | None
    updated_at: datetime
    last_error: str | None
    last_run_id: int | None

    model_config = ConfigDict(extra="forbid")


class QueueListData(BaseModel):
    queue_items: list[QueueItemData]

    model_config = ConfigDict(extra="forbid")


class QueueListEnvelope(BaseModel):
    data: QueueListData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class QueueItemEnvelope(BaseModel):
    data: QueueItemData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class QueueClearData(BaseModel):
    queue_item_id: int
    previous_status: str
    status: str
    message: str

    model_config = ConfigDict(extra="forbid")


class QueueClearEnvelope(BaseModel):
    data: QueueClearData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


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
    email: str
    password: str
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
    new_password: str

    model_config = ConfigDict(extra="forbid")


class SettingsData(BaseModel):
    auto_run_enabled: bool
    run_interval_minutes: int
    request_delay_seconds: int
    nav_visible_pages: list[str]

    model_config = ConfigDict(extra="forbid")


class SettingsEnvelope(BaseModel):
    data: SettingsData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class SettingsUpdateRequest(BaseModel):
    auto_run_enabled: bool
    run_interval_minutes: int
    request_delay_seconds: int
    nav_visible_pages: list[str] | None = None

    model_config = ConfigDict(extra="forbid")


class PublicationItemData(BaseModel):
    publication_id: int
    scholar_profile_id: int
    scholar_label: str
    title: str
    year: int | None
    citation_count: int
    venue_text: str | None
    pub_url: str | None
    is_read: bool
    first_seen_at: datetime
    is_new_in_latest_run: bool

    model_config = ConfigDict(extra="forbid")


class PublicationsListData(BaseModel):
    mode: str
    selected_scholar_profile_id: int | None
    new_count: int
    total_count: int
    publications: list[PublicationItemData]

    model_config = ConfigDict(extra="forbid")


class PublicationsListEnvelope(BaseModel):
    data: PublicationsListData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class MarkAllReadData(BaseModel):
    message: str
    updated_count: int

    model_config = ConfigDict(extra="forbid")


class MarkAllReadEnvelope(BaseModel):
    data: MarkAllReadData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class PublicationSelectionItem(BaseModel):
    scholar_profile_id: int
    publication_id: int

    model_config = ConfigDict(extra="forbid")


class MarkSelectedReadRequest(BaseModel):
    selections: list[PublicationSelectionItem] = Field(min_length=1, max_length=500)

    model_config = ConfigDict(extra="forbid")


class MarkSelectedReadData(BaseModel):
    message: str
    requested_count: int
    updated_count: int

    model_config = ConfigDict(extra="forbid")


class MarkSelectedReadEnvelope(BaseModel):
    data: MarkSelectedReadData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")
