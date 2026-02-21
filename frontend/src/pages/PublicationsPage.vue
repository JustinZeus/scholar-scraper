<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppPage from "@/components/layout/AppPage.vue";
import AsyncStateGate from "@/components/patterns/AsyncStateGate.vue";
import RequestStateAlerts from "@/components/patterns/RequestStateAlerts.vue";
import AppBadge from "@/components/ui/AppBadge.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppRefreshButton from "@/components/ui/AppRefreshButton.vue";
import AppSelect from "@/components/ui/AppSelect.vue";
import AppTable from "@/components/ui/AppTable.vue";
import {
  listPublications,
  markAllRead,
  markSelectedRead,
  retryPublicationPdf,
  togglePublicationFavorite,
  type PublicationItem,
  type PublicationMode,
  type PublicationsResult,
} from "@/features/publications";
import { listScholars, type ScholarProfile } from "@/features/scholars";
import { ApiRequestError } from "@/lib/api/errors";
import { useRunStatusStore } from "@/stores/run_status";
import { useUserSettingsStore } from "@/stores/user_settings";

type PublicationSortKey =
  | "title"
  | "favorite"
  | "scholar"
  | "year"
  | "citations"
  | "status"
  | "first_seen";

type BulkAction =
  | "mark_selected_read"
  | "mark_all_unread_read"
  | "select_all_visible_unread"
  | "clear_selection";
type BulkActionOption = { value: BulkAction; label: string };

const loading = ref(true);
const publishingAll = ref(false);
const publishingSelected = ref(false);
const mode = ref<PublicationMode>("all");
const favoriteOnly = ref(false);
const bulkAction = ref<BulkAction>("mark_all_unread_read");
const selectedScholarFilter = ref("");
const searchQuery = ref("");
const sortKey = ref<PublicationSortKey>("first_seen");
const sortDirection = ref<"asc" | "desc">("desc");
const currentPage = ref(1);
const pageSize = ref("50");

const scholars = ref<ScholarProfile[]>([]);
const listState = ref<PublicationsResult | null>(null);
const selectedPublicationKeys = ref<Set<string>>(new Set());
const retryingPublicationKeys = ref<Set<string>>(new Set());
const favoriteUpdatingKeys = ref<Set<string>>(new Set());

const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);
const route = useRoute();
const router = useRouter();
const textCollator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });
const runStatus = useRunStatusStore();
const userSettings = useUserSettingsStore();

function normalizeScholarFilterQuery(value: unknown): string {
  if (Array.isArray(value)) {
    return normalizeScholarFilterQuery(value[0]);
  }
  if (typeof value !== "string") {
    return "";
  }
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? String(parsed) : "";
}

function normalizeFavoriteOnlyQuery(value: unknown): boolean {
  if (Array.isArray(value)) {
    return normalizeFavoriteOnlyQuery(value[0]);
  }
  if (typeof value !== "string") {
    return false;
  }
  const normalized = value.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes";
}

function normalizePageQuery(value: unknown): number {
  if (Array.isArray(value)) {
    return normalizePageQuery(value[0]);
  }
  if (typeof value !== "string") {
    return 1;
  }
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 1;
}

function syncFiltersFromRoute(): boolean {
  let changed = false;
  const nextScholar = normalizeScholarFilterQuery(route.query.scholar);
  const nextFavoriteOnly = normalizeFavoriteOnlyQuery(route.query.favorite);
  const nextPage = normalizePageQuery(route.query.page);
  if (selectedScholarFilter.value !== nextScholar) {
    selectedScholarFilter.value = nextScholar;
    changed = true;
  }
  if (favoriteOnly.value !== nextFavoriteOnly) {
    favoriteOnly.value = nextFavoriteOnly;
    changed = true;
  }
  if (currentPage.value !== nextPage) {
    currentPage.value = nextPage;
    changed = true;
  }
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

function formatDate(value: string): string {
  const asDate = new Date(value);
  if (Number.isNaN(asDate.getTime())) {
    return value;
  }
  return asDate.toLocaleDateString();
}

function publicationKey(item: PublicationItem): string {
  return `${item.scholar_profile_id}:${item.publication_id}`;
}

function scholarLabel(item: ScholarProfile): string {
  return item.display_name || item.scholar_id;
}

function publicationPrimaryUrl(item: PublicationItem): string | null {
  return item.pub_url || item.pdf_url;
}

function publicationDoiUrl(item: PublicationItem): string | null {
  if (!item.doi) {
    return null;
  }
  return `https://doi.org/${item.doi}`;
}

const selectedScholarName = computed(() => {
  const selectedId = Number(selectedScholarFilter.value);
  if (!Number.isInteger(selectedId) || selectedId <= 0) {
    return "all scholars";
  }
  const profile = scholars.value.find((item) => item.id === selectedId);
  return profile ? scholarLabel(profile) : "the selected scholar";
});

const filteredPublications = computed(() => {
  const base = listState.value?.publications ?? [];
  const normalized = searchQuery.value.trim().toLowerCase();
  if (!normalized) {
    return base;
  }
  return base.filter((item) => {
    const year = item.year === null ? "" : String(item.year);
    return [item.title, item.scholar_label, item.venue_text || "", year]
      .join(" ")
      .toLowerCase()
      .includes(normalized);
  });
});

function publicationSortValue(item: PublicationItem, key: PublicationSortKey): number | string {
  if (key === "title") {
    return item.title;
  }
  if (key === "favorite") {
    return item.is_favorite ? 1 : 0;
  }
  if (key === "scholar") {
    return item.scholar_label;
  }
  if (key === "year") {
    return item.year ?? -1;
  }
  if (key === "citations") {
    return item.citation_count;
  }
  if (key === "status") {
    if (item.is_read) {
      return 2;
    }
    if (item.is_new_in_latest_run) {
      return 0;
    }
    return 1;
  }
  const timestamp = Date.parse(item.first_seen_at);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

const sortedPublications = computed(() => {
  const sorted = [...filteredPublications.value];
  sorted.sort((a, b) => {
    const left = publicationSortValue(a, sortKey.value);
    const right = publicationSortValue(b, sortKey.value);

    let comparison: number;
    if (typeof left === "string" && typeof right === "string") {
      comparison = textCollator.compare(left, right);
    } else {
      comparison = Number(left) - Number(right);
    }

    if (comparison === 0) {
      comparison = textCollator.compare(a.title, b.title);
    }
    return sortDirection.value === "asc" ? comparison : comparison * -1;
  });
  return sorted;
});

const visibleUnreadKeys = computed(() => {
  const keys = new Set<string>();
  for (const item of sortedPublications.value) {
    if (!item.is_read) {
      keys.add(publicationKey(item));
    }
  }
  return keys;
});

const pageSizeValue = computed(() => {
  const parsed = Number(pageSize.value);
  if (!Number.isInteger(parsed)) {
    return 50;
  }
  return Math.max(10, Math.min(200, parsed));
});
const hasNextPage = computed(() => Boolean(listState.value?.has_next));
const hasPrevPage = computed(() => Boolean(listState.value?.has_prev));
const totalPages = computed(() => {
  if (!listState.value) {
    return 1;
  }
  return Math.max(1, Math.ceil(listState.value.total_count / Math.max(listState.value.page_size, 1)));
});

const selectedCount = computed(() => selectedPublicationKeys.value.size);
const visibleCount = computed(() => sortedPublications.value.length);
const visibleUnreadCount = computed(() => visibleUnreadKeys.value.size);
const visibleFavoriteCount = computed(
  () => sortedPublications.value.filter((item) => item.is_favorite).length,
);
const actionBusy = computed(() => loading.value || publishingAll.value || publishingSelected.value);
const startRunDisabledReason = computed(() => {
  if (!userSettings.manualRunAllowed) {
    return "Manual runs are disabled by policy.";
  }
  if (runStatus.safetyState.cooldown_active) {
    return runStatus.safetyState.cooldown_reason_label || "Safety cooldown is active.";
  }
  if (runStatus.isRunActive) {
    return "A run is already in progress.";
  }
  return null;
});
const startRunButtonLabel = computed(() => {
  if (runStatus.isSubmitting) {
    return "Starting...";
  }
  if (!userSettings.manualRunAllowed) {
    return "Manual runs disabled";
  }
  if (runStatus.safetyState.cooldown_active) {
    return "Safety cooldown";
  }
  if (runStatus.isLikelyRunning) {
    return "Run active";
  }
  return "Start run";
});
const startRunDisabled = computed(() => Boolean(startRunDisabledReason.value) || runStatus.isSubmitting);
const hasSelection = computed(() => selectedCount.value > 0);
const bulkActionOptions = computed<BulkActionOption[]>(() => {
  if (hasSelection.value) {
    return [
      {
        value: "mark_selected_read",
        label: `Mark selected as read (${selectedCount.value})`,
      },
      {
        value: "clear_selection",
        label: `Clear selection (${selectedCount.value})`,
      },
    ];
  }
  return [
    { value: "mark_all_unread_read", label: "Mark all unread as read" },
    { value: "select_all_visible_unread", label: "Select all visible unread" },
  ];
});
const bulkApplyDisabled = computed(() => {
  if (actionBusy.value) {
    return true;
  }
  if (bulkAction.value === "mark_selected_read" || bulkAction.value === "clear_selection") {
    return selectedCount.value === 0;
  }
  if (bulkAction.value === "mark_all_unread_read" || bulkAction.value === "select_all_visible_unread") {
    return visibleUnreadCount.value === 0;
  }
  return false;
});
const bulkApplyLabel = computed(() => {
  if (publishingSelected.value || publishingAll.value) {
    return "Applying...";
  }
  if (bulkAction.value === "select_all_visible_unread") {
    return "Select";
  }
  if (bulkAction.value === "clear_selection") {
    return "Clear";
  }
  return "Apply";
});
const showingEmptyList = computed(() => Boolean(listState.value) && sortedPublications.value.length === 0);
const scopeLabel = computed(() => {
  if (mode.value === "latest" && favoriteOnly.value) {
    return "New + Favorites";
  }
  if (mode.value === "latest") {
    return "New";
  }
  if (mode.value === "unread" && favoriteOnly.value) {
    return "Unread + Favorites";
  }
  if (mode.value === "unread") {
    return "Unread";
  }
  if (favoriteOnly.value) {
    return "All + Favorites";
  }
  return "All";
});

const emptyTitle = computed(() =>
  searchQuery.value.trim().length > 0 ? "No publications match this search" : "No publications found",
);

const emptyBody = computed(() => {
  if (searchQuery.value.trim().length > 0) {
    return "Try another title, scholar, venue, or year.";
  }
  if (favoriteOnly.value && mode.value === "latest") {
    return `No new favorites for ${selectedScholarName.value}.`;
  }
  if (mode.value === "latest") {
    return `No new publications in the latest run for ${selectedScholarName.value}.`;
  }
  if (favoriteOnly.value && mode.value === "unread") {
    return `No unread favorites for ${selectedScholarName.value}.`;
  }
  if (favoriteOnly.value) {
    return `No favorites for ${selectedScholarName.value}.`;
  }
  if (mode.value === "unread") {
    return `No unread publications for ${selectedScholarName.value}.`;
  }
  return `No publication records for ${selectedScholarName.value}.`;
});

const allVisibleUnreadSelected = computed(() => {
  if (visibleUnreadKeys.value.size === 0) {
    return false;
  }
  for (const key of visibleUnreadKeys.value) {
    if (!selectedPublicationKeys.value.has(key)) {
      return false;
    }
  }
  return true;
});

watch(sortedPublications, (items) => {
  const validKeys = new Set(items.filter((item) => !item.is_read).map((item) => publicationKey(item)));
  const next = new Set<string>();
  for (const key of selectedPublicationKeys.value) {
    if (validKeys.has(key)) {
      next.add(key);
    }
  }
  if (next.size !== selectedPublicationKeys.value.size) {
    selectedPublicationKeys.value = next;
  }
});

watch(hasSelection, (nextHasSelection) => {
  const validValues = new Set(bulkActionOptions.value.map((item) => item.value));
  if (validValues.has(bulkAction.value)) {
    return;
  }
  bulkAction.value = nextHasSelection ? "mark_selected_read" : "mark_all_unread_read";
});

function toggleSort(nextKey: PublicationSortKey): void {
  if (sortKey.value === nextKey) {
    sortDirection.value = sortDirection.value === "asc" ? "desc" : "asc";
    return;
  }
  sortKey.value = nextKey;
  sortDirection.value = nextKey === "first_seen" ? "desc" : "asc";
}

function sortMarker(key: PublicationSortKey): string {
  if (sortKey.value !== key) {
    return "↕";
  }
  return sortDirection.value === "asc" ? "↑" : "↓";
}

async function loadScholarFilters(): Promise<void> {
  try {
    scholars.value = await listScholars();
  } catch {
    scholars.value = [];
  }
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
      page: currentPage.value,
      pageSize: pageSizeValue.value,
    });
    currentPage.value = listState.value.page;
    pageSize.value = String(listState.value.page_size);
    selectedPublicationKeys.value = new Set();
  } catch (error) {
    listState.value = null;
    selectedPublicationKeys.value = new Set();
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

async function onModeChanged(): Promise<void> {
  currentPage.value = 1;
  await syncFiltersToRoute();
  await loadPublications();
}

async function onScholarFilterChanged(): Promise<void> {
  currentPage.value = 1;
  await syncFiltersToRoute();
  await loadPublications();
}

async function onFavoriteOnlyChanged(): Promise<void> {
  favoriteOnly.value = !favoriteOnly.value;
  currentPage.value = 1;
  await syncFiltersToRoute();
  await loadPublications();
}

async function onPageSizeChanged(): Promise<void> {
  currentPage.value = 1;
  await syncFiltersToRoute();
  await loadPublications();
}

async function onPrevPage(): Promise<void> {
  if (!hasPrevPage.value || currentPage.value <= 1) {
    return;
  }
  currentPage.value -= 1;
  await syncFiltersToRoute();
  await loadPublications();
}

async function onNextPage(): Promise<void> {
  if (!hasNextPage.value) {
    return;
  }
  currentPage.value += 1;
  await syncFiltersToRoute();
  await loadPublications();
}

function selectAllVisibleUnread(): void {
  selectedPublicationKeys.value = new Set(visibleUnreadKeys.value);
}

function clearSelection(): void {
  selectedPublicationKeys.value = new Set();
}

async function onApplyBulkAction(): Promise<void> {
  if (bulkApplyDisabled.value) {
    return;
  }
  if (bulkAction.value === "select_all_visible_unread") {
    selectAllVisibleUnread();
    return;
  }
  if (bulkAction.value === "clear_selection") {
    clearSelection();
    return;
  }
  if (bulkAction.value === "mark_selected_read") {
    await onMarkSelectedRead();
    return;
  }
  await onMarkAllRead();
}

function onToggleAllVisible(event: Event): void {
  const checked = (event.target as HTMLInputElement).checked;
  const next = new Set(selectedPublicationKeys.value);
  for (const key of visibleUnreadKeys.value) {
    if (checked) {
      next.add(key);
    } else {
      next.delete(key);
    }
  }
  selectedPublicationKeys.value = next;
}

function onToggleRowSelection(item: PublicationItem, event: Event): void {
  const checked = (event.target as HTMLInputElement).checked;
  const key = publicationKey(item);
  const next = new Set(selectedPublicationKeys.value);
  if (checked) {
    next.add(key);
  } else {
    next.delete(key);
  }
  selectedPublicationKeys.value = next;
}

function isRetryingPublication(item: PublicationItem): boolean {
  return retryingPublicationKeys.value.has(publicationKey(item));
}

function isFavoriteUpdating(item: PublicationItem): boolean {
  return favoriteUpdatingKeys.value.has(publicationKey(item));
}

function canRetryPublicationPdf(item: PublicationItem): boolean {
  return !item.pdf_url && item.pdf_status === "failed" && item.pdf_attempt_count > 0;
}

function pdfPendingLabel(item: PublicationItem): string {
  if (item.pdf_status === "queued") {
    return "queued";
  }
  if (item.pdf_status === "running") {
    return "resolving";
  }
  if (item.pdf_status === "failed") {
    return "failed";
  }
  return "untracked";
}

function replacePublication(updated: PublicationItem): void {
  if (!listState.value) {
    return;
  }
  listState.value.publications = listState.value.publications.map((item) => {
    if (publicationKey(item) !== publicationKey(updated)) {
      return item;
    }
    return updated;
  });
}

function withFavorite(item: PublicationItem, isFavorite: boolean): PublicationItem {
  return {
    ...item,
    is_favorite: isFavorite,
  };
}

async function onToggleFavorite(item: PublicationItem): Promise<void> {
  if (isFavoriteUpdating(item)) {
    return;
  }
  const key = publicationKey(item);
  const nextFavorite = !item.is_favorite;
  const nextUpdating = new Set(favoriteUpdatingKeys.value);
  nextUpdating.add(key);
  favoriteUpdatingKeys.value = nextUpdating;
  errorMessage.value = null;
  errorRequestId.value = null;

  replacePublication(withFavorite(item, nextFavorite));

  try {
    const response = await togglePublicationFavorite(
      item.publication_id,
      item.scholar_profile_id,
      nextFavorite,
    );
    replacePublication(response.publication);
  } catch (error) {
    replacePublication(withFavorite(item, item.is_favorite));
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to update favorite state.";
    }
  } finally {
    const cleared = new Set(favoriteUpdatingKeys.value);
    cleared.delete(key);
    favoriteUpdatingKeys.value = cleared;
  }
}

async function onRetryPdf(item: PublicationItem): Promise<void> {
  if (item.pdf_url || !canRetryPublicationPdf(item)) {
    return;
  }
  const key = publicationKey(item);
  const next = new Set(retryingPublicationKeys.value);
  next.add(key);
  retryingPublicationKeys.value = next;
  errorMessage.value = null;
  errorRequestId.value = null;
  successMessage.value = null;

  try {
    const response = await retryPublicationPdf(item.publication_id, item.scholar_profile_id);
    replacePublication(response.publication);
    successMessage.value = response.message;
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to retry PDF lookup for this publication.";
    }
  } finally {
    const cleared = new Set(retryingPublicationKeys.value);
    cleared.delete(key);
    retryingPublicationKeys.value = cleared;
  }
}

async function onMarkSelectedRead(): Promise<void> {
  if (selectedPublicationKeys.value.size === 0 || !listState.value) {
    return;
  }

  const selectedLookup = new Set(selectedPublicationKeys.value);
  const selections = listState.value.publications
    .filter((item) => selectedLookup.has(publicationKey(item)))
    .map((item) => ({
      scholar_profile_id: item.scholar_profile_id,
      publication_id: item.publication_id,
    }));

  publishingSelected.value = true;
  successMessage.value = null;
  errorMessage.value = null;
  errorRequestId.value = null;

  try {
    const response = await markSelectedRead(selections);
    successMessage.value = `${response.updated_count} publication${response.updated_count === 1 ? "" : "s"} marked as read.`;
    await loadPublications();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to mark selected publications as read.";
    }
  } finally {
    publishingSelected.value = false;
  }
}

async function onMarkAllRead(): Promise<void> {
  publishingAll.value = true;
  successMessage.value = null;
  errorMessage.value = null;
  errorRequestId.value = null;

  try {
    const response = await markAllRead();
    successMessage.value = `${response.updated_count} publication${response.updated_count === 1 ? "" : "s"} marked as read.`;
    await loadPublications();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to mark publications as read.";
    }
  } finally {
    publishingAll.value = false;
  }
}

async function onStartRun(): Promise<void> {
  if (startRunDisabled.value) {
    return;
  }
  successMessage.value = null;
  errorMessage.value = null;
  errorRequestId.value = null;

  const result = await runStatus.startManualCheck();
  if (result.kind === "started") {
    successMessage.value = `Run #${result.runId} started.`;
    return;
  }
  if (result.kind === "already_running") {
    successMessage.value = result.runId
      ? `Run #${result.runId} is already in progress.`
      : "A run is already in progress.";
    return;
  }
  errorMessage.value = result.message;
  errorRequestId.value = result.requestId;
}

function resetSearchQuery(): void {
  searchQuery.value = "";
}

onMounted(() => {
  syncFiltersFromRoute();
  void Promise.all([loadScholarFilters(), loadPublications(), runStatus.syncLatest()]);
});

watch(
  () => [route.query.scholar, route.query.favorite, route.query.page],
  async () => {
    const changed = syncFiltersFromRoute();
    if (!changed) {
      return;
    }
    await loadPublications();
  },
);
</script>

<template>
  <AppPage title="Publications" subtitle="Review discoveries, open PDFs, and update read/favorite state in one workspace.">
    <AppCard class="space-y-4">
      <div class="grid gap-3 xl:grid-cols-[minmax(0,13rem)_minmax(0,18rem)_minmax(0,1fr)_auto] xl:items-end">
        <div class="grid gap-1 text-xs text-secondary">
          <div class="flex items-center gap-1">
            <span>Status</span>
            <AppHelpHint text="All shows full history. Unread and New narrow the dataset before search." />
          </div>
          <AppSelect v-model="mode" :disabled="actionBusy" @change="onModeChanged">
            <option value="all">All records</option>
            <option value="unread">Unread</option>
            <option value="latest">New (latest run)</option>
          </AppSelect>
        </div>

        <label class="grid gap-1 text-xs text-secondary" for="publications-scholar-filter">
          <span class="inline-flex items-center gap-1">
            Scholar
            <AppHelpHint text="Filter to one tracked scholar profile. Filter is synced to URL query." />
          </span>
          <AppSelect
            id="publications-scholar-filter"
            v-model="selectedScholarFilter"
            :disabled="actionBusy"
            @change="onScholarFilterChanged"
          >
            <option value="">All scholars</option>
            <option v-for="scholar in scholars" :key="scholar.id" :value="String(scholar.id)">
              {{ scholarLabel(scholar) }}
            </option>
          </AppSelect>
        </label>

        <label class="grid gap-1 text-xs text-secondary" for="publications-search-input">
          <span class="inline-flex items-center gap-1">
            Search
            <AppHelpHint text="Searches title, scholar, venue, and year within currently loaded results." />
          </span>
          <div class="flex min-w-0 items-center gap-2">
            <AppInput
              id="publications-search-input"
              v-model="searchQuery"
              placeholder="Search title, scholar, venue, year"
              :disabled="loading"
            />
            <AppButton
              v-if="searchQuery.trim().length > 0"
              variant="secondary"
              class="shrink-0"
              :disabled="loading"
              @click="resetSearchQuery"
            >
              Clear
            </AppButton>
          </div>
        </label>

        <div class="flex flex-wrap items-end justify-end gap-2">
          <button
            type="button"
            class="favorite-filter-button"
            :class="favoriteOnly ? 'favorite-filter-on' : 'favorite-filter-off'"
            :disabled="actionBusy"
            :title="favoriteOnly ? 'Favorites-only filter is active' : 'Show only favorites'"
            :aria-pressed="favoriteOnly"
            :aria-label="favoriteOnly ? 'Disable favorites-only filter' : 'Enable favorites-only filter'"
            @click="onFavoriteOnlyChanged"
          >
            <span aria-hidden="true">{{ favoriteOnly ? "★" : "☆" }}</span>
          </button>
          <AppButton
            variant="secondary"
            :disabled="startRunDisabled"
            :title="startRunDisabledReason || undefined"
            @click="onStartRun"
          >
            {{ startRunButtonLabel }}
          </AppButton>
          <AppRefreshButton
            variant="ghost"
            :disabled="loading"
            :loading="loading"
            title="Refresh publications"
            loading-title="Refreshing publications"
            @click="loadPublications"
          />
        </div>
      </div>

      <RequestStateAlerts
        :success-message="successMessage"
        success-title="Publication update complete"
        :error-message="errorMessage"
        :error-request-id="errorRequestId"
        error-title="Publication request failed"
        @dismiss-success="successMessage = null"
      />

      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-stroke-default pt-3">
        <div class="flex items-center gap-1">
          <h3 class="text-base font-semibold text-ink-primary">Results</h3>
          <AppHelpHint
            text="Star to favorite, open PDF when available, and retry only after failed PDF lookup attempts."
          />
        </div>
        <div class="flex flex-wrap items-center justify-end gap-2 text-[11px] text-secondary">
          <span>Scope: {{ scopeLabel }} | Showing {{ selectedScholarName }}</span>
          <div class="flex items-center gap-1">
            <label for="publications-page-size" class="sr-only">Page size</label>
            <AppSelect
              id="publications-page-size"
              v-model="pageSize"
              :disabled="loading"
              class="max-w-[8rem] !py-1.5 !text-xs"
              @change="onPageSizeChanged"
            >
              <option value="25">25 / page</option>
              <option value="50">50 / page</option>
              <option value="100">100 / page</option>
              <option value="200">200 / page</option>
            </AppSelect>
            <AppHelpHint
              text="When no rows are selected, actions target all unread results. After selecting rows, the menu switches to selected-row actions."
            />
            <label for="publications-bulk-action" class="sr-only">Bulk task</label>
            <AppSelect
              id="publications-bulk-action"
              v-model="bulkAction"
              :disabled="actionBusy"
              class="max-w-[14rem] !py-1.5 !text-xs"
            >
              <option v-for="option in bulkActionOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </AppSelect>
            <AppButton
              variant="secondary"
              class="h-8 min-h-8 shrink-0 px-2 text-xs"
              :disabled="bulkApplyDisabled"
              @click="onApplyBulkAction"
            >
              {{ bulkApplyLabel }}
            </AppButton>
          </div>
        </div>
      </div>

      <AsyncStateGate
        :loading="loading"
        :loading-lines="8"
        :empty="showingEmptyList"
        :empty-title="emptyTitle"
        :empty-body="emptyBody"
        :show-empty="!errorMessage"
      >
        <AppTable v-if="listState" label="Publication list table">
          <thead>
            <tr>
              <th scope="col" class="w-10">
                <input
                  type="checkbox"
                  class="h-4 w-4 rounded border-stroke-interactive bg-surface-input text-brand-600 focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset"
                  :checked="allVisibleUnreadSelected"
                  :disabled="visibleUnreadKeys.size === 0"
                  aria-label="Select all visible unread publications"
                  @change="onToggleAllVisible"
                />
              </th>
              <th scope="col" class="w-12">
                <button type="button" class="table-sort" @click="toggleSort('favorite')">
                  ★ <span aria-hidden="true" class="sort-marker">{{ sortMarker('favorite') }}</span>
                </button>
              </th>
              <th scope="col" class="w-[44%] min-w-[24rem]">
                <button type="button" class="table-sort" @click="toggleSort('title')">
                  Title <span aria-hidden="true" class="sort-marker">{{ sortMarker('title') }}</span>
                </button>
              </th>
              <th scope="col" class="w-[16%] min-w-[12rem]">
                <button type="button" class="table-sort" @click="toggleSort('scholar')">
                  Scholar <span aria-hidden="true" class="sort-marker">{{ sortMarker('scholar') }}</span>
                </button>
              </th>
              <th scope="col" class="w-[8.5rem] whitespace-nowrap">PDF</th>
              <th scope="col" class="w-16 whitespace-nowrap">
                <button type="button" class="table-sort" @click="toggleSort('year')">
                  Year <span aria-hidden="true" class="sort-marker">{{ sortMarker('year') }}</span>
                </button>
              </th>
              <th scope="col" class="w-24 whitespace-nowrap">
                <button type="button" class="table-sort" @click="toggleSort('citations')">
                  Citations <span aria-hidden="true" class="sort-marker">{{ sortMarker('citations') }}</span>
                </button>
              </th>
              <th scope="col" class="w-44 whitespace-nowrap">
                <button type="button" class="table-sort" @click="toggleSort('status')">
                  Read status <span aria-hidden="true" class="sort-marker">{{ sortMarker('status') }}</span>
                </button>
              </th>
              <th scope="col" class="w-32 whitespace-nowrap">
                <button type="button" class="table-sort" @click="toggleSort('first_seen')">
                  First seen <span aria-hidden="true" class="sort-marker">{{ sortMarker('first_seen') }}</span>
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in sortedPublications" :key="publicationKey(item)">
              <td>
                <input
                  type="checkbox"
                  class="h-4 w-4 rounded border-stroke-interactive bg-surface-input text-brand-600 focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset"
                  :checked="selectedPublicationKeys.has(publicationKey(item))"
                  :disabled="item.is_read"
                  :aria-label="`Select publication ${item.title}`"
                  @change="onToggleRowSelection(item, $event)"
                />
              </td>
              <td>
                <button
                  type="button"
                  class="favorite-star-button"
                  :class="item.is_favorite ? 'favorite-star-on' : 'favorite-star-off'"
                  :aria-label="item.is_favorite ? `Remove ${item.title} from favorites` : `Add ${item.title} to favorites`"
                  :aria-pressed="item.is_favorite"
                  :disabled="isFavoriteUpdating(item)"
                  @click="onToggleFavorite(item)"
                >
                  {{ item.is_favorite ? "★" : "☆" }}
                </button>
              </td>
              <td class="max-w-0">
                <div class="grid min-w-0 gap-1">
                  <a
                    v-if="publicationPrimaryUrl(item)"
                    :href="publicationPrimaryUrl(item) || ''"
                    target="_blank"
                    rel="noreferrer"
                    class="link-inline block truncate font-medium"
                    :title="item.title"
                  >
                    {{ item.title }}
                  </a>
                  <span v-else class="block truncate font-medium" :title="item.title">{{ item.title }}</span>
                  <a
                    v-if="publicationDoiUrl(item)"
                    :href="publicationDoiUrl(item) || ''"
                    target="_blank"
                    rel="noreferrer"
                    class="link-inline block truncate text-xs"
                    :title="`DOI: ${item.doi}`"
                  >
                    DOI: {{ item.doi }}
                  </a>
                </div>
              </td>
              <td>
                <span class="block truncate" :title="item.scholar_label">{{ item.scholar_label }}</span>
              </td>
              <td class="whitespace-nowrap">
                <a
                  v-if="item.pdf_url"
                  :href="item.pdf_url"
                  target="_blank"
                  rel="noreferrer"
                  class="pdf-link-button"
                >
                  PDF
                </a>
                <button
                  v-else-if="canRetryPublicationPdf(item)"
                  type="button"
                  class="pdf-retry-button"
                  :disabled="isRetryingPublication(item)"
                  @click="onRetryPdf(item)"
                >
                  {{ isRetryingPublication(item) ? "..." : "retry" }}
                </button>
                <span v-else class="pdf-state-label">{{ pdfPendingLabel(item) }}</span>
              </td>
              <td class="whitespace-nowrap">{{ item.year ?? "n/a" }}</td>
              <td class="whitespace-nowrap">{{ item.citation_count }}</td>
              <td>
                <div class="status-badges-row">
                  <AppBadge :tone="item.is_new_in_latest_run ? 'info' : 'neutral'">
                    {{ item.is_new_in_latest_run ? "New" : "Seen" }}
                  </AppBadge>
                  <AppBadge :tone="item.is_read ? 'success' : 'warning'">
                    {{ item.is_read ? "Read" : "Unread" }}
                  </AppBadge>
                </div>
              </td>
              <td class="whitespace-nowrap">{{ formatDate(item.first_seen_at) }}</td>
            </tr>
          </tbody>
        </AppTable>
      </AsyncStateGate>

      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-stroke-default pt-2 text-xs text-secondary">
        <span>
          visible {{ visibleCount }} · unread {{ visibleUnreadCount }} · favorites {{ visibleFavoriteCount }}
          · selected {{ selectedCount }}
        </span>
        <div class="flex items-center gap-2">
          <span>page {{ currentPage }} / {{ totalPages }}</span>
          <AppButton variant="ghost" class="h-8 min-h-8 px-2" :disabled="!hasPrevPage || loading" @click="onPrevPage">
            Prev
          </AppButton>
          <AppButton variant="ghost" class="h-8 min-h-8 px-2" :disabled="!hasNextPage || loading" @click="onNextPage">
            Next
          </AppButton>
        </div>
      </div>
    </AppCard>
  </AppPage>
</template>

<style scoped>
.table-sort {
  @apply flex w-full items-center justify-between gap-2 text-left font-semibold text-ink-primary transition hover:text-ink-link focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset;
}

.sort-marker {
  @apply text-[11px] leading-none text-ink-muted;
}

.favorite-filter-button {
  @apply inline-flex min-h-10 h-10 w-10 items-center justify-center rounded-full border text-base leading-none transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset disabled:cursor-not-allowed disabled:opacity-50;
}

.favorite-filter-on {
  @apply border-warning-300 bg-warning-100 text-warning-700 hover:bg-warning-200;
}

.favorite-filter-off {
  @apply border-stroke-default bg-surface-card-muted text-ink-muted hover:border-stroke-interactive hover:text-ink-secondary;
}

.favorite-star-button {
  @apply inline-flex h-7 w-7 items-center justify-center rounded-full border text-sm leading-none transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset disabled:cursor-not-allowed disabled:opacity-50;
}

.favorite-star-on {
  @apply border-warning-300 bg-warning-100 text-warning-700 hover:bg-warning-200;
}

.favorite-star-off {
  @apply border-stroke-default bg-surface-card-muted text-ink-muted hover:border-stroke-interactive hover:text-ink-secondary;
}

.pdf-link-button {
  @apply inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium border-state-success-border bg-state-success-bg text-state-success-text shadow-sm transition hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset;
}

.pdf-retry-button {
  @apply inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium border-state-warning-border bg-state-warning-bg text-state-warning-text transition hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset disabled:cursor-not-allowed disabled:opacity-50;
}

.pdf-state-label {
  @apply inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium border-stroke-default bg-surface-card-muted text-secondary;
}

.status-badges-row {
  @apply inline-flex items-center gap-1 whitespace-nowrap;
}
</style>
