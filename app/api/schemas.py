from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    doi: str | None = None
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


class DataImportRequest(BaseModel):
    schema_version: int | None = None
    scholars: list[ScholarExportItemData] = Field(default_factory=list)
    publications: list[PublicationExportItemData] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


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
    safety_state: ScrapeSafetyStateData

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


class ScrapeSafetyCountersData(BaseModel):
    consecutive_blocked_runs: int = 0
    consecutive_network_runs: int = 0
    cooldown_entry_count: int = 0
    blocked_start_count: int = 0
    last_blocked_failure_count: int = 0
    last_network_failure_count: int = 0
    last_evaluated_run_id: int | None = None

    model_config = ConfigDict(extra="forbid")


class ScrapeSafetyStateData(BaseModel):
    cooldown_active: bool
    cooldown_reason: str | None = None
    cooldown_reason_label: str | None = None
    cooldown_until: datetime | None = None
    cooldown_remaining_seconds: int = 0
    recommended_action: str | None = None
    counters: ScrapeSafetyCountersData = Field(default_factory=ScrapeSafetyCountersData)

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
    safety_state: ScrapeSafetyStateData

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
    safety_state: ScrapeSafetyStateData

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


class DisplayIdentifierData(BaseModel):
    kind: str
    value: str
    label: str
    url: str | None
    confidence_score: float = Field(ge=0.0, le=1.0)

    model_config = ConfigDict(extra="forbid")


class AdminPdfQueueItemData(BaseModel):
    publication_id: int
    title: str
    doi: str | None
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
    def validate_scope(self) -> "AdminRepairPublicationLinksRequest":
        if self.scope_mode == "single_user" and self.user_id is None:
            raise ValueError("user_id is required when scope_mode=single_user.")
        if self.scope_mode == "all_users" and self.user_id is not None:
            raise ValueError("user_id must be omitted when scope_mode=all_users.")
        if not self.dry_run and self.scope_mode == "all_users":
            expected = "REPAIR ALL USERS"
            provided = (self.confirmation_text or "").strip()
            if provided != expected:
                raise ValueError(
                    "confirmation_text must equal 'REPAIR ALL USERS' "
                    "when applying a repair to all users."
                )
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


class SettingsPolicyData(BaseModel):
    min_run_interval_minutes: int
    min_request_delay_seconds: int
    automation_allowed: bool
    manual_run_allowed: bool
    blocked_failure_threshold: int
    network_failure_threshold: int
    cooldown_blocked_seconds: int
    cooldown_network_seconds: int

    model_config = ConfigDict(extra="forbid")


class SettingsData(BaseModel):
    auto_run_enabled: bool
    run_interval_minutes: int
    request_delay_seconds: int
    nav_visible_pages: list[str]
    policy: SettingsPolicyData
    safety_state: ScrapeSafetyStateData

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
    doi: str | None
    display_identifier: DisplayIdentifierData | None = None
    pdf_url: str | None
    pdf_status: str = "untracked"
    pdf_attempt_count: int = 0
    pdf_failure_reason: str | None = None
    pdf_failure_detail: str | None = None
    is_read: bool
    is_favorite: bool = False
    first_seen_at: datetime
    is_new_in_latest_run: bool

    model_config = ConfigDict(extra="forbid")


class PublicationsListData(BaseModel):
    mode: str
    favorite_only: bool = False
    selected_scholar_profile_id: int | None
    unread_count: int
    favorites_count: int
    latest_count: int
    new_count: int
    total_count: int
    page: int
    page_size: int
    has_next: bool = False
    has_prev: bool = False
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


class RetryPublicationPdfRequest(BaseModel):
    scholar_profile_id: int = Field(ge=1)

    model_config = ConfigDict(extra="forbid")


class RetryPublicationPdfData(BaseModel):
    message: str
    queued: bool
    resolved_pdf: bool
    publication: PublicationItemData

    model_config = ConfigDict(extra="forbid")


class RetryPublicationPdfEnvelope(BaseModel):
    data: RetryPublicationPdfData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")


class TogglePublicationFavoriteRequest(BaseModel):
    scholar_profile_id: int = Field(ge=1)
    is_favorite: bool

    model_config = ConfigDict(extra="forbid")


class TogglePublicationFavoriteData(BaseModel):
    message: str
    publication: PublicationItemData

    model_config = ConfigDict(extra="forbid")


class TogglePublicationFavoriteEnvelope(BaseModel):
    data: TogglePublicationFavoriteData
    meta: ApiMeta

    model_config = ConfigDict(extra="forbid")
