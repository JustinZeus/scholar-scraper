import { apiRequest } from "@/lib/api/client";

export interface RunListItem {
  id: number;
  trigger_type: string;
  status: string;
  start_dt: string;
  end_dt: string | null;
  scholar_count: number;
  new_publication_count: number;
  failed_count: number;
  partial_count: number;
}

export interface RunSummary {
  succeeded_count: number;
  failed_count: number;
  partial_count: number;
  failed_state_counts: Record<string, number>;
  failed_reason_counts: Record<string, number>;
}

export interface RunScholarResult {
  scholar_profile_id: number;
  scholar_id: string;
  state: string;
  state_reason: string | null;
  outcome: string;
  attempt_count: number;
  publication_count: number;
  start_cstart: number;
  continuation_cstart: number | null;
  continuation_enqueued: boolean;
  continuation_cleared: boolean;
  warnings: string[];
  error: string | null;
  debug: Record<string, unknown> | null;
}

export interface RunDetail {
  run: RunListItem;
  summary: RunSummary;
  scholar_results: RunScholarResult[];
}

export interface QueueItem {
  id: number;
  scholar_profile_id: number;
  scholar_label: string;
  status: string;
  reason: string;
  dropped_reason: string | null;
  attempt_count: number;
  resume_cstart: number;
  next_attempt_dt: string | null;
  updated_at: string;
  last_error: string | null;
  last_run_id: number | null;
}

interface RunsListData {
  runs: RunListItem[];
}

interface QueueListData {
  queue_items: QueueItem[];
}

export interface RunsListQuery {
  failedOnly?: boolean;
  limit?: number;
}

export async function listRuns(query: RunsListQuery = {}): Promise<RunListItem[]> {
  const params = new URLSearchParams();
  if (query.failedOnly) {
    params.set("failed_only", "true");
  }
  if (query.limit) {
    params.set("limit", String(query.limit));
  }

  const suffix = params.toString();
  const response = await apiRequest<RunsListData>(`/runs${suffix ? `?${suffix}` : ""}`, {
    method: "GET",
  });
  return response.data.runs;
}

export async function getRunDetail(runId: number): Promise<RunDetail> {
  const response = await apiRequest<RunDetail>(`/runs/${runId}`, { method: "GET" });
  return response.data;
}

function generateIdempotencyKey(): string {
  const randomUuid = globalThis.crypto?.randomUUID?.();
  if (randomUuid) {
    return randomUuid;
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export async function triggerManualRun(): Promise<{
  run_id: number;
  status: string;
  scholar_count: number;
  succeeded_count: number;
  failed_count: number;
  partial_count: number;
  new_publication_count: number;
  reused_existing_run: boolean;
  idempotency_key: string | null;
}> {
  const headers: Record<string, string> = {
    "Idempotency-Key": generateIdempotencyKey(),
  };

  const response = await apiRequest<{
    run_id: number;
    status: string;
    scholar_count: number;
    succeeded_count: number;
    failed_count: number;
    partial_count: number;
    new_publication_count: number;
    reused_existing_run: boolean;
    idempotency_key: string | null;
  }>("/runs/manual", {
    method: "POST",
    headers,
  });
  return response.data;
}

export async function listQueueItems(limit = 200): Promise<QueueItem[]> {
  const response = await apiRequest<QueueListData>(`/runs/queue/items?limit=${limit}`, {
    method: "GET",
  });
  return response.data.queue_items;
}

export async function retryQueueItem(queueItemId: number): Promise<QueueItem> {
  const response = await apiRequest<QueueItem>(`/runs/queue/${queueItemId}/retry`, {
    method: "POST",
  });
  return response.data;
}

export async function dropQueueItem(queueItemId: number): Promise<QueueItem> {
  const response = await apiRequest<QueueItem>(`/runs/queue/${queueItemId}/drop`, {
    method: "POST",
  });
  return response.data;
}

export async function clearQueueItem(queueItemId: number): Promise<{
  queue_item_id: number;
  previous_status: string;
  status: string;
  message: string;
}> {
  const response = await apiRequest<{
    queue_item_id: number;
    previous_status: string;
    status: string;
    message: string;
  }>(`/runs/queue/${queueItemId}`, {
    method: "DELETE",
  });
  return response.data;
}
