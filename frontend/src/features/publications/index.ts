import { apiRequest } from "@/lib/api/client";

export type PublicationMode = "all" | "unread" | "latest";

export interface DisplayIdentifier {
  kind: string;
  value: string;
  label: string;
  url: string | null;
  confidence_score: number;
}

export interface PublicationItem {
  publication_id: number;
  scholar_profile_id: number;
  scholar_label: string;
  title: string;
  year: number | null;
  citation_count: number;
  venue_text: string | null;
  pub_url: string | null;
  doi: string | null;
  display_identifier: DisplayIdentifier | null;
  pdf_url: string | null;
  pdf_status: "untracked" | "queued" | "running" | "resolved" | "failed";
  pdf_attempt_count: number;
  pdf_failure_reason: string | null;
  pdf_failure_detail: string | null;
  is_read: boolean;
  is_favorite: boolean;
  first_seen_at: string;
  is_new_in_latest_run: boolean;
}

export interface PublicationsResult {
  mode: PublicationMode;
  favorite_only: boolean;
  selected_scholar_profile_id: number | null;
  unread_count: number;
  favorites_count: number;
  latest_count: number;
  // Compatibility alias for latest_count; retained while API clients migrate.
  new_count: number;
  total_count: number;
  page: number;
  page_size: number;
  has_next: boolean;
  has_prev: boolean;
  publications: PublicationItem[];
}

export interface PublicationsQuery {
  mode?: PublicationMode;
  favoriteOnly?: boolean;
  scholarProfileId?: number;
  page?: number;
  pageSize?: number;
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
  if (query.favoriteOnly) {
    params.set("favorite_only", "true");
  }
  if (query.scholarProfileId) {
    params.set("scholar_profile_id", String(query.scholarProfileId));
  }
  const parsedPage = Number.isFinite(query.page) ? Math.max(1, Math.trunc(Number(query.page))) : 1;
  const parsedPageSize = Number.isFinite(query.pageSize)
    ? Math.max(1, Math.min(500, Math.trunc(Number(query.pageSize))))
    : 100;
  params.set("page", String(parsedPage));
  params.set("page_size", String(parsedPageSize));

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

export interface RetryPublicationPdfResult {
  message: string;
  queued: boolean;
  resolved_pdf: boolean;
  publication: PublicationItem;
}

export interface TogglePublicationFavoriteResult {
  message: string;
  publication: PublicationItem;
}

export async function retryPublicationPdf(
  publicationId: number,
  scholarProfileId: number,
): Promise<RetryPublicationPdfResult> {
  const response = await apiRequest<RetryPublicationPdfResult>(
    `/publications/${publicationId}/retry-pdf`,
    {
      method: "POST",
      body: { scholar_profile_id: scholarProfileId },
    },
  );
  return response.data;
}

export async function togglePublicationFavorite(
  publicationId: number,
  scholarProfileId: number,
  isFavorite: boolean,
): Promise<TogglePublicationFavoriteResult> {
  const response = await apiRequest<TogglePublicationFavoriteResult>(
    `/publications/${publicationId}/favorite`,
    {
      method: "POST",
      body: {
        scholar_profile_id: scholarProfileId,
        is_favorite: isFavorite,
      },
    },
  );
  return response.data;
}
