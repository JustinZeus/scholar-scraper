import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  listPublications,
  type PublicationItem,
  type PublicationMode,
  type PublicationsResult,
} from "@/features/publications";
import { listScholars, type ScholarProfile } from "@/features/scholars";
import { ApiRequestError } from "@/lib/api/errors";
import { useRunStatusStore } from "@/stores/run_status";

export type PublicationSortKey =
  | "title"
  | "scholar"
  | "year"
  | "citations"
  | "first_seen"
  | "pdf_status";

export function publicationKey(item: PublicationItem): string {
  return `${item.scholar_profile_id}:${item.publication_id}`;
}

export function usePublicationData() {
  const loading = ref(true);
  const mode = ref<PublicationMode>("all");
  const favoriteOnly = ref(false);
  const selectedScholarFilter = ref("");
  const searchQuery = ref("");
  const sortKey = ref<PublicationSortKey>("first_seen");
  const sortDirection = ref<"asc" | "desc">("desc");
  const currentPage = ref(1);
  const pageSize = ref("50");
  const publicationSnapshot = ref<string | null>(null);

  const scholars = ref<ScholarProfile[]>([]);
  const listState = ref<PublicationsResult | null>(null);

  const errorMessage = ref<string | null>(null);
  const errorRequestId = ref<string | null>(null);
  const successMessage = ref<string | null>(null);
  const route = useRoute();
  const router = useRouter();
  const textCollator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });
  const runStatus = useRunStatusStore();

  // --- Route sync ---

  function normalizeScholarFilterQuery(value: unknown): string {
    if (Array.isArray(value)) return normalizeScholarFilterQuery(value[0]);
    if (typeof value !== "string") return "";
    const parsed = Number(value);
    return Number.isInteger(parsed) && parsed > 0 ? String(parsed) : "";
  }

  function normalizeFavoriteOnlyQuery(value: unknown): boolean {
    if (Array.isArray(value)) return normalizeFavoriteOnlyQuery(value[0]);
    if (typeof value !== "string") return false;
    const normalized = value.trim().toLowerCase();
    return normalized === "1" || normalized === "true" || normalized === "yes";
  }

  function normalizePageQuery(value: unknown): number {
    if (Array.isArray(value)) return normalizePageQuery(value[0]);
    if (typeof value !== "string") return 1;
    const parsed = Number(value);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : 1;
  }

  function syncFiltersFromRoute(): boolean {
    let changed = false;
    const nextScholar = normalizeScholarFilterQuery(route.query.scholar);
    const nextFavoriteOnly = normalizeFavoriteOnlyQuery(route.query.favorite);
    const nextPage = normalizePageQuery(route.query.page);
    if (selectedScholarFilter.value !== nextScholar) { selectedScholarFilter.value = nextScholar; changed = true; }
    if (favoriteOnly.value !== nextFavoriteOnly) { favoriteOnly.value = nextFavoriteOnly; changed = true; }
    if (currentPage.value !== nextPage) { currentPage.value = nextPage; changed = true; }
    return changed;
  }

  async function syncFiltersToRoute(): Promise<void> {
    const nextScholar = selectedScholarFilter.value.trim();
    const currentScholar = normalizeScholarFilterQuery(route.query.scholar);
    const currentFavoriteOnly = normalizeFavoriteOnlyQuery(route.query.favorite);
    const currentPageQuery = normalizePageQuery(route.query.page);
    if (
      nextScholar === currentScholar
      && favoriteOnly.value === currentFavoriteOnly
      && currentPage.value === currentPageQuery
    ) {
      return;
    }
    await router.replace({
      query: {
        ...route.query,
        scholar: nextScholar || undefined,
        favorite: favoriteOnly.value ? "1" : undefined,
        page: currentPage.value > 1 ? String(currentPage.value) : undefined,
      },
    });
  }

  // --- Sorting helpers ---

  function publicationSortValue(item: PublicationItem, key: PublicationSortKey): number | string {
    if (key === "title") return item.title;
    if (key === "scholar") return item.scholar_label;
    if (key === "year") return item.year ?? -1;
    if (key === "citations") return item.citation_count;
    if (key === "pdf_status") {
      if (item.pdf_url || item.pdf_status === "resolved") return 4;
      if (item.pdf_status === "running") return 3;
      if (item.pdf_status === "queued") return 2;
      if (item.pdf_status === "failed") return 0;
      return 1;
    }
    const timestamp = Date.parse(item.first_seen_at);
    return Number.isNaN(timestamp) ? 0 : timestamp;
  }

  // --- Computed ---

  const selectedScholarName = computed(() => {
    const selectedId = Number(selectedScholarFilter.value);
    if (!Number.isInteger(selectedId) || selectedId <= 0) return "all scholars";
    const profile = scholars.value.find((item) => item.id === selectedId);
    return profile ? (profile.display_name || profile.scholar_id) : "the selected scholar";
  });

  const filteredPublications = computed(() => {
    let stream = [...runStatus.livePublications];
    if (favoriteOnly.value) stream = stream.filter((p) => p.is_favorite);
    if (mode.value === "unread") stream = stream.filter((p) => !p.is_read);
    const selectedScholarId = Number(selectedScholarFilter.value);
    if (Number.isInteger(selectedScholarId) && selectedScholarId > 0) {
      stream = stream.filter((p) => p.scholar_profile_id === selectedScholarId);
    }
    const base = listState.value?.publications ?? [];
    const merged = [...stream, ...base];
    const seenKeys = new Set<string>();
    const deduped: typeof base = [];
    for (const item of merged) {
      const key = publicationKey(item);
      if (!seenKeys.has(key)) { seenKeys.add(key); deduped.push(item); }
    }
    return deduped;
  });

  const sortedPublications = computed(() => {
    const direction = sortDirection.value === "asc" ? 1 : -1;
    return [...filteredPublications.value].sort((left, right) => {
      const leftValue = publicationSortValue(left, sortKey.value);
      const rightValue = publicationSortValue(right, sortKey.value);
      let comparison = 0;
      if (typeof leftValue === "string" && typeof rightValue === "string") {
        comparison = textCollator.compare(leftValue, rightValue);
      } else {
        comparison = Number(leftValue) - Number(rightValue);
      }
      if (comparison !== 0) return comparison * direction;
      return right.publication_id - left.publication_id;
    });
  });

  const visibleUnreadKeys = computed(() => {
    const keys = new Set<string>();
    for (const item of sortedPublications.value) {
      if (!item.is_read) keys.add(publicationKey(item));
    }
    return keys;
  });

  const pageSizeValue = computed(() => {
    const parsed = Number(pageSize.value);
    if (!Number.isInteger(parsed)) return 50;
    return Math.max(10, Math.min(200, parsed));
  });
  const hasNextPage = computed(() => Boolean(listState.value?.has_next));
  const hasPrevPage = computed(() => Boolean(listState.value?.has_prev));
  const totalPages = computed(() => {
    if (!listState.value) return 1;
    return Math.max(1, Math.ceil(listState.value.total_count / Math.max(listState.value.page_size, 1)));
  });
  const totalCount = computed(() => listState.value?.total_count ?? 0);
  const visibleCount = computed(() => sortedPublications.value.length);
  const visibleUnreadCount = computed(() => visibleUnreadKeys.value.size);
  const visibleFavoriteCount = computed(
    () => sortedPublications.value.filter((item) => item.is_favorite).length,
  );

  // --- Data loading ---

  async function loadScholarFilters(): Promise<void> {
    try { scholars.value = await listScholars(); } catch { scholars.value = []; }
  }

  function selectedScholarId(): number | undefined {
    const parsed = Number(selectedScholarFilter.value);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
  }

  async function loadPublications(): Promise<void> {
    loading.value = true;
    errorMessage.value = null;
    errorRequestId.value = null;
    try {
      listState.value = await listPublications({
        mode: mode.value,
        favoriteOnly: favoriteOnly.value,
        scholarProfileId: selectedScholarId(),
        search: searchQuery.value.trim() || undefined,
        sortBy: sortKey.value,
        sortDir: sortDirection.value,
        page: currentPage.value,
        pageSize: pageSizeValue.value,
        snapshot: publicationSnapshot.value ?? undefined,
      });
      publicationSnapshot.value = listState.value.snapshot;
      currentPage.value = listState.value.page;
      pageSize.value = String(listState.value.page_size);
    } catch (error) {
      listState.value = null;
      if (error instanceof ApiRequestError) {
        errorMessage.value = error.message;
        errorRequestId.value = error.requestId;
      } else {
        errorMessage.value = "Unable to load publications.";
      }
    } finally {
      loading.value = false;
    }
  }

  function resetPageAndSnapshot(): void {
    currentPage.value = 1;
    publicationSnapshot.value = null;
  }

  async function toggleSort(nextKey: PublicationSortKey): Promise<void> {
    if (sortKey.value === nextKey) {
      sortDirection.value = sortDirection.value === "asc" ? "desc" : "asc";
    } else {
      sortKey.value = nextKey;
      sortDirection.value = nextKey === "first_seen" || nextKey === "pdf_status" ? "desc" : "asc";
    }
    resetPageAndSnapshot();
    await loadPublications();
  }

  function sortMarker(key: PublicationSortKey): string {
    if (sortKey.value !== key) return "↕";
    return sortDirection.value === "asc" ? "↑" : "↓";
  }

  function replacePublication(updated: PublicationItem): void {
    if (!listState.value) return;
    listState.value.publications = listState.value.publications.map((item) =>
      publicationKey(item) !== publicationKey(updated) ? item : updated,
    );
  }

  // --- Search debounce watcher setup ---

  let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  watch(searchQuery, () => {
    if (searchDebounceTimer !== null) clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
      resetPageAndSnapshot();
      void loadPublications();
    }, 300);
  });

  // --- Run-triggered refresh watcher ---

  watch(
    () => runStatus.latestRun,
    async (nextRun, previousRun) => {
      const nextRunId = nextRun && (nextRun.status === "running" || nextRun.status === "resolving") ? nextRun.id : null;
      const previousRunId = previousRun && (previousRun.status === "running" || previousRun.status === "resolving") ? previousRun.id : null;
      if (nextRunId === null || nextRunId === previousRunId) return;
      resetPageAndSnapshot();
      await loadPublications();
    },
  );

  // --- Route watcher ---

  watch(
    () => [route.query.scholar, route.query.favorite, route.query.page],
    async () => {
      const previousScholar = selectedScholarFilter.value;
      const previousFavorite = favoriteOnly.value;
      const changed = syncFiltersFromRoute();
      if (!changed) return;
      if (selectedScholarFilter.value !== previousScholar || favoriteOnly.value !== previousFavorite) {
        publicationSnapshot.value = null;
      }
      await loadPublications();
    },
  );

  return {
    loading,
    mode,
    favoriteOnly,
    selectedScholarFilter,
    searchQuery,
    sortKey,
    sortDirection,
    currentPage,
    pageSize,
    scholars,
    listState,
    errorMessage,
    errorRequestId,
    successMessage,
    selectedScholarName,
    sortedPublications,
    visibleUnreadKeys,
    pageSizeValue,
    hasNextPage,
    hasPrevPage,
    totalPages,
    totalCount,
    visibleCount,
    visibleUnreadCount,
    visibleFavoriteCount,
    loadScholarFilters,
    loadPublications,
    resetPageAndSnapshot,
    toggleSort,
    sortMarker,
    replacePublication,
    syncFiltersFromRoute,
    syncFiltersToRoute,
  };
}
