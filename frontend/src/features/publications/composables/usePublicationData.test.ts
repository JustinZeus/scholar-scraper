import { describe, expect, it, vi, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";

vi.mock("vue-router", () => ({
  useRoute: vi.fn(() => ({ query: {} })),
  useRouter: vi.fn(() => ({ replace: vi.fn() })),
}));

vi.mock("@/features/publications", async (importOriginal) => {
  const original = (await importOriginal()) as Record<string, unknown>;
  return {
    ...original,
    listPublications: vi.fn(),
  };
});

vi.mock("@/features/scholars", () => ({
  listScholars: vi.fn(),
}));

import { listPublications } from "@/features/publications";
import { listScholars } from "@/features/scholars";
import { usePublicationData } from "./usePublicationData";

const mockedListPublications = vi.mocked(listPublications);
const mockedListScholars = vi.mocked(listScholars);

describe("usePublicationData", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    mockedListPublications.mockReset();
    mockedListScholars.mockReset();
  });

  it("initializes with default filter values", () => {
    const data = usePublicationData();
    expect(data.mode.value).toBe("all");
    expect(data.favoriteOnly.value).toBe(false);
    expect(data.searchQuery.value).toBe("");
    expect(data.selectedScholarFilter.value).toBe("");
    expect(data.loading.value).toBe(true);
  });

  it("loadScholarFilters calls listScholars", async () => {
    mockedListScholars.mockResolvedValueOnce([
      { id: 1, scholar_id: "abc", display_name: "Test", profile_image_url: null, profile_image_source: "none" as const, is_enabled: true, baseline_completed: true, last_run_dt: null, last_run_status: null },
    ]);
    const data = usePublicationData();
    await data.loadScholarFilters();
    expect(mockedListScholars).toHaveBeenCalled();
    expect(data.scholars.value).toHaveLength(1);
  });

  it("loadPublications calls listPublications with current filters", async () => {
    mockedListPublications.mockResolvedValueOnce({
      publications: [],
      mode: "all" as const,
      favorite_only: false,
      selected_scholar_profile_id: null,
      unread_count: 0,
      favorites_count: 0,
      latest_count: 0,
      new_count: 0,
      total_count: 0,
      page: 1,
      page_size: 25,
      snapshot: "",
      has_next: false,
      has_prev: false,
    });
    const data = usePublicationData();
    await data.loadPublications();
    expect(mockedListPublications).toHaveBeenCalled();
  });

  it("resetPageAndSnapshot resets page to 1", () => {
    const data = usePublicationData();
    data.currentPage.value = 5;
    data.resetPageAndSnapshot();
    expect(data.currentPage.value).toBe(1);
  });

  it("toggleSort reverses direction for same key", async () => {
    mockedListPublications.mockResolvedValue({
      publications: [],
      mode: "all" as const,
      favorite_only: false,
      selected_scholar_profile_id: null,
      unread_count: 0,
      favorites_count: 0,
      latest_count: 0,
      new_count: 0,
      total_count: 0,
      page: 1,
      page_size: 25,
      snapshot: "",
      has_next: false,
      has_prev: false,
    });
    const data = usePublicationData();
    const initialDirection = data.sortDirection.value;
    await data.toggleSort(data.sortKey.value);
    expect(data.sortDirection.value).toBe(initialDirection === "asc" ? "desc" : "asc");
  });

  it("sortMarker returns arrow indicators", () => {
    const data = usePublicationData();
    expect(data.sortMarker(data.sortKey.value)).toMatch(/[↑↓]/);
    expect(data.sortMarker("year" as never)).toBe("↕");
  });

  it("computed pagination properties work correctly", () => {
    const data = usePublicationData();
    expect(data.hasPrevPage.value).toBe(false);
    expect(data.totalPages.value).toBe(1);
    expect(data.totalCount.value).toBe(0);
  });
});
