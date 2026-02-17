import { apiRequest } from "@/lib/api/client";

export type PublicationMode = "all" | "new";

export interface PublicationItem {
  publication_id: number;
  scholar_profile_id: number;
  scholar_label: string;
  title: string;
  year: number | null;
  citation_count: number;
  venue_text: string | null;
  pub_url: string | null;
  is_read: boolean;
  first_seen_at: string;
  is_new_in_latest_run: boolean;
}

export interface PublicationsResult {
  mode: PublicationMode;
  selected_scholar_profile_id: number | null;
  new_count: number;
  total_count: number;
  publications: PublicationItem[];
}

export interface PublicationsQuery {
  mode?: PublicationMode;
  scholarProfileId?: number;
  limit?: number;
}

export interface PublicationSelection {
  scholar_profile_id: number;
  publication_id: number;
}

export async function listPublications(query: PublicationsQuery = {}): Promise<PublicationsResult> {
  const params = new URLSearchParams();

  if (query.mode) {
    params.set("mode", query.mode);
  }
  if (query.scholarProfileId) {
    params.set("scholar_profile_id", String(query.scholarProfileId));
  }
  if (query.limit) {
    params.set("limit", String(query.limit));
  }

  const suffix = params.toString();
  const response = await apiRequest<PublicationsResult>(
    `/publications${suffix ? `?${suffix}` : ""}`,
    { method: "GET" },
  );
  return response.data;
}

export async function markAllRead(): Promise<{ message: string; updated_count: number }> {
  const response = await apiRequest<{ message: string; updated_count: number }>(
    "/publications/mark-all-read",
    { method: "POST" },
  );
  return response.data;
}

export async function markSelectedRead(selections: PublicationSelection[]): Promise<{
  message: string;
  requested_count: number;
  updated_count: number;
}> {
  const response = await apiRequest<{
    message: string;
    requested_count: number;
    updated_count: number;
  }>("/publications/mark-read", {
    method: "POST",
    body: { selections },
  });
  return response.data;
}
