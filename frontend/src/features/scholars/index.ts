import { apiRequest } from "@/lib/api/client";

export interface ScholarProfile {
  id: number;
  scholar_id: string;
  display_name: string | null;
  profile_image_url: string | null;
  profile_image_source: "upload" | "override" | "scraped" | "none";
  is_enabled: boolean;
  baseline_completed: boolean;
  last_run_dt: string | null;
  last_run_status: string | null;
}

export interface ScholarCreatePayload {
  scholar_id: string;
  profile_image_url?: string;
}

export interface ScholarSearchCandidate {
  scholar_id: string;
  display_name: string;
  affiliation: string | null;
  email_domain: string | null;
  cited_by_count: number | null;
  interests: string[];
  profile_url: string;
  profile_image_url: string | null;
}

export interface ScholarSearchResult {
  query: string;
  state: "ok" | "no_results" | "blocked_or_captcha" | "layout_changed" | "network_error";
  state_reason: string;
  action_hint: string | null;
  candidates: ScholarSearchCandidate[];
  warnings: string[];
}

export interface ScholarExportItem {
  scholar_id: string;
  display_name: string | null;
  is_enabled: boolean;
  profile_image_override_url: string | null;
}

export interface PublicationExportItem {
  scholar_id: string;
  cluster_id: string | null;
  fingerprint_sha256: string | null;
  title: string;
  year: number | null;
  citation_count: number;
  author_text: string | null;
  venue_text: string | null;
  pub_url: string | null;
  pdf_url: string | null;
  is_read: boolean;
}

export interface DataExportPayload {
  schema_version: number;
  exported_at: string;
  scholars: ScholarExportItem[];
  publications: PublicationExportItem[];
}

export interface DataImportPayload {
  schema_version?: number;
  scholars: ScholarExportItem[];
  publications: PublicationExportItem[];
}

export interface DataImportResult {
  scholars_created: number;
  scholars_updated: number;
  publications_created: number;
  publications_updated: number;
  links_created: number;
  links_updated: number;
  skipped_records: number;
}

interface ScholarsListData {
  scholars: ScholarProfile[];
}

interface ScholarSearchData extends ScholarSearchResult {}

export async function listScholars(): Promise<ScholarProfile[]> {
  const response = await apiRequest<ScholarsListData>("/scholars", { method: "GET" });
  return response.data.scholars;
}

export async function createScholar(payload: ScholarCreatePayload): Promise<ScholarProfile> {
  const response = await apiRequest<ScholarProfile>("/scholars", {
    method: "POST",
    body: payload,
  });
  return response.data;
}

export async function toggleScholar(scholarProfileId: number): Promise<ScholarProfile> {
  const response = await apiRequest<ScholarProfile>(`/scholars/${scholarProfileId}/toggle`, {
    method: "PATCH",
  });
  return response.data;
}

export async function deleteScholar(scholarProfileId: number): Promise<void> {
  await apiRequest<{ message: string }>(`/scholars/${scholarProfileId}`, {
    method: "DELETE",
  });
}

export async function searchScholarsByName(
  query: string,
  limit = 10,
): Promise<ScholarSearchResult> {
  const searchParams = new URLSearchParams({
    query,
    limit: String(limit),
  });
  const response = await apiRequest<ScholarSearchData>(`/scholars/search?${searchParams.toString()}`, {
    method: "GET",
  });
  return response.data;
}

export async function setScholarImageUrl(
  scholarProfileId: number,
  imageUrl: string,
): Promise<ScholarProfile> {
  const response = await apiRequest<ScholarProfile>(`/scholars/${scholarProfileId}/image/url`, {
    method: "PUT",
    body: { image_url: imageUrl },
  });
  return response.data;
}

export async function uploadScholarImage(
  scholarProfileId: number,
  file: File,
): Promise<ScholarProfile> {
  const form = new FormData();
  form.append("image", file);
  const response = await apiRequest<ScholarProfile>(`/scholars/${scholarProfileId}/image/upload`, {
    method: "POST",
    body: form,
  });
  return response.data;
}

export async function clearScholarImage(
  scholarProfileId: number,
): Promise<ScholarProfile> {
  const response = await apiRequest<ScholarProfile>(`/scholars/${scholarProfileId}/image`, {
    method: "DELETE",
  });
  return response.data;
}

export async function exportScholarData(): Promise<DataExportPayload> {
  const response = await apiRequest<DataExportPayload>("/scholars/export", {
    method: "GET",
  });
  return response.data;
}

export async function importScholarData(
  payload: DataImportPayload,
): Promise<DataImportResult> {
  const response = await apiRequest<DataImportResult>("/scholars/import", {
    method: "POST",
    body: payload,
  });
  return response.data;
}
