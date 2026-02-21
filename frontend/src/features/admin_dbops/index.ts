import { apiRequest } from "@/lib/api/client";

export interface AdminDbIntegrityCheck {
  name: string;
  count: number;
  severity: "warning" | "failure" | "metric";
  message: string;
}

export interface AdminDbIntegrityReport {
  status: "ok" | "warning" | "failed";
  checked_at: string;
  failures: string[];
  warnings: string[];
  checks: AdminDbIntegrityCheck[];
}

export interface AdminDbRepairJob {
  id: number;
  job_name: string;
  requested_by: string | null;
  dry_run: boolean;
  status: string;
  scope: Record<string, unknown>;
  summary: Record<string, unknown>;
  error_text: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminPdfQueueItem {
  publication_id: number;
  title: string;
  doi: string | null;
  pdf_url: string | null;
  status: string;
  attempt_count: number;
  last_failure_reason: string | null;
  last_failure_detail: string | null;
  last_source: string | null;
  requested_by_user_id: number | null;
  requested_by_email: string | null;
  queued_at: string | null;
  last_attempt_at: string | null;
  resolved_at: string | null;
  updated_at: string;
}

export interface AdminPdfQueuePage {
  items: AdminPdfQueueItem[];
  total_count: number;
  page: number;
  page_size: number;
  has_next: boolean;
  has_prev: boolean;
}

export interface AdminPdfQueueRequeueResult {
  publication_id: number;
  queued: boolean;
  status: string;
  message: string;
}

export interface AdminPdfQueueBulkEnqueueResult {
  requested_count: number;
  queued_count: number;
  message: string;
}

export interface TriggerPublicationLinkRepairPayload {
  scope_mode?: "single_user" | "all_users";
  user_id?: number;
  scholar_profile_ids?: number[];
  dry_run?: boolean;
  gc_orphan_publications?: boolean;
  requested_by?: string;
  confirmation_text?: string;
}

export interface TriggerPublicationLinkRepairResult {
  job_id: number;
  status: string;
  scope: Record<string, unknown>;
  summary: Record<string, unknown>;
}

export async function getAdminDbIntegrityReport(): Promise<AdminDbIntegrityReport> {
  const response = await apiRequest<AdminDbIntegrityReport>("/admin/db/integrity", { method: "GET" });
  return response.data;
}

export async function listAdminDbRepairJobs(limit = 30): Promise<AdminDbRepairJob[]> {
  const parsedLimit = Number.isFinite(limit) ? Math.max(1, Math.min(200, Math.trunc(limit))) : 30;
  const response = await apiRequest<{ jobs: AdminDbRepairJob[] }>(
    `/admin/db/repair-jobs?limit=${parsedLimit}`,
    { method: "GET" },
  );
  return response.data.jobs;
}

export async function triggerPublicationLinkRepair(
  payload: TriggerPublicationLinkRepairPayload,
): Promise<TriggerPublicationLinkRepairResult> {
  const response = await apiRequest<TriggerPublicationLinkRepairResult>(
    "/admin/db/repairs/publication-links",
    {
      method: "POST",
      body: payload,
    },
  );
  return response.data;
}

export async function listAdminPdfQueue(
  page = 1,
  pageSize = 100,
  status: string | null = null,
): Promise<AdminPdfQueuePage> {
  const parsedPage = Number.isFinite(page) ? Math.max(1, Math.trunc(page)) : 1;
  const parsedPageSize = Number.isFinite(pageSize) ? Math.max(1, Math.min(500, Math.trunc(pageSize))) : 100;
  const params = new URLSearchParams();
  params.set("page", String(parsedPage));
  params.set("page_size", String(parsedPageSize));
  if (status && status.trim().length > 0) {
    params.set("status", status.trim().toLowerCase());
  }
  const response = await apiRequest<AdminPdfQueuePage>(
    `/admin/db/pdf-queue?${params.toString()}`,
    { method: "GET" },
  );
  return response.data;
}

export async function requeueAdminPdfLookup(publicationId: number): Promise<AdminPdfQueueRequeueResult> {
  const id = Number.isFinite(publicationId) ? Math.trunc(publicationId) : 0;
  const response = await apiRequest<AdminPdfQueueRequeueResult>(
    `/admin/db/pdf-queue/${Math.max(1, id)}/requeue`,
    { method: "POST" },
  );
  return response.data;
}

export async function requeueAllAdminPdfLookups(limit = 1000): Promise<AdminPdfQueueBulkEnqueueResult> {
  const parsedLimit = Number.isFinite(limit) ? Math.max(1, Math.min(5000, Math.trunc(limit))) : 1000;
  const response = await apiRequest<AdminPdfQueueBulkEnqueueResult>(
    `/admin/db/pdf-queue/requeue-all?limit=${parsedLimit}`,
    { method: "POST" },
  );
  return response.data;
}
