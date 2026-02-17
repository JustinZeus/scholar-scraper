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
