<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import AppPage from "@/components/layout/AppPage.vue";
import AsyncStateGate from "@/components/patterns/AsyncStateGate.vue";
import RequestStateAlerts from "@/components/patterns/RequestStateAlerts.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppSelect from "@/components/ui/AppSelect.vue";
import AppTable from "@/components/ui/AppTable.vue";
import {
  markAllRead,
  markSelectedRead,
  retryPublicationPdf,
  togglePublicationFavorite,
  type PublicationItem,
} from "@/features/publications";
import PublicationTableRow from "@/features/publications/components/PublicationTableRow.vue";
import PublicationToolbar from "@/features/publications/components/PublicationToolbar.vue";
import { publicationKey, usePublicationData } from "@/features/publications/composables/usePublicationData";
import { ApiRequestError } from "@/lib/api/errors";
import { useRunStatusStore } from "@/stores/run_status";
import { useUserSettingsStore } from "@/stores/user_settings";

type BulkAction = "mark_selected_read" | "mark_all_unread_read" | "select_all_visible_unread" | "clear_selection";
type BulkActionOption = { value: BulkAction; label: string };

const pub = usePublicationData();
const runStatus = useRunStatusStore();
const userSettings = useUserSettingsStore();

const publishingAll = ref(false);
const publishingSelected = ref(false);
const bulkAction = ref<BulkAction>("mark_all_unread_read");
const selectedPublicationKeys = ref<Set<string>>(new Set());
const retryingPublicationKeys = ref<Set<string>>(new Set());
const favoriteUpdatingKeys = ref<Set<string>>(new Set());

const PUBLICATIONS_RUN_STATUS_SYNC_INTERVAL_MS = 5000;
let runStatusSyncTimer: ReturnType<typeof setInterval> | null = null;

function startRunStatusSyncLoop(): void {
  if (runStatusSyncTimer !== null) return;
  runStatusSyncTimer = setInterval(() => {
    if (runStatus.isRunActive) return;
    void runStatus.syncLatest();
  }, PUBLICATIONS_RUN_STATUS_SYNC_INTERVAL_MS);
}

function stopRunStatusSyncLoop(): void {
  if (runStatusSyncTimer === null) return;
  clearInterval(runStatusSyncTimer);
  runStatusSyncTimer = null;
}

// --- Computed ---

const selectedCount = computed(() => selectedPublicationKeys.value.size);
const actionBusy = computed(() => pub.loading.value || publishingAll.value || publishingSelected.value);
const startRunDisabledReason = computed(() => {
  if (!userSettings.manualRunAllowed) return "Manual runs are disabled by policy.";
  if (runStatus.safetyState.cooldown_active) {
    return runStatus.safetyState.cooldown_reason_label || "Safety cooldown is active.";
  }
  if (runStatus.isRunActive) return "A run is already in progress.";
  return null;
});
const startRunButtonLabel = computed(() => {
  if (runStatus.isSubmitting) return "Starting...";
  if (!userSettings.manualRunAllowed) return "Manual runs disabled";
  if (runStatus.safetyState.cooldown_active) return "Safety cooldown";
  if (runStatus.isLikelyRunning) return "Run active";
  return "Start run";
});
const startRunDisabled = computed(() => Boolean(startRunDisabledReason.value) || runStatus.isSubmitting);
const hasSelection = computed(() => selectedCount.value > 0);
const bulkActionOptions = computed<BulkActionOption[]>(() => {
  if (hasSelection.value) {
    return [
      { value: "mark_selected_read", label: `Mark selected as read (${selectedCount.value})` },
      { value: "clear_selection", label: `Clear selection (${selectedCount.value})` },
    ];
  }
  return [
    { value: "mark_all_unread_read", label: "Mark all unread as read" },
    { value: "select_all_visible_unread", label: "Select all visible unread" },
  ];
});
const bulkApplyDisabled = computed(() => {
  if (actionBusy.value) return true;
  if (bulkAction.value === "mark_selected_read" || bulkAction.value === "clear_selection") {
    return selectedCount.value === 0;
  }
  if (bulkAction.value === "mark_all_unread_read" || bulkAction.value === "select_all_visible_unread") {
    return pub.visibleUnreadCount.value === 0;
  }
  return false;
});
const bulkApplyLabel = computed(() => {
  if (publishingSelected.value || publishingAll.value) return "Applying...";
  if (bulkAction.value === "select_all_visible_unread") return "Select";
  if (bulkAction.value === "clear_selection") return "Clear";
  return "Apply";
});
const showingEmptyList = computed(() => Boolean(pub.listState.value) && pub.sortedPublications.value.length === 0);
const scopeLabel = computed(() => {
  if (pub.mode.value === "latest" && pub.favoriteOnly.value) return "New + Favorites";
  if (pub.mode.value === "latest") return "New";
  if (pub.mode.value === "unread" && pub.favoriteOnly.value) return "Unread + Favorites";
  if (pub.mode.value === "unread") return "Unread";
  if (pub.favoriteOnly.value) return "All + Favorites";
  return "All";
});
const emptyTitle = computed(() =>
  pub.searchQuery.value.trim().length > 0 ? "No publications match this search" : "No publications found",
);
const emptyBody = computed(() => {
  if (pub.searchQuery.value.trim().length > 0) return "Try another title, scholar, venue, or year.";
  if (pub.favoriteOnly.value && pub.mode.value === "latest") return `No new favorites for ${pub.selectedScholarName.value}.`;
  if (pub.mode.value === "latest") return `No new publications in the latest run for ${pub.selectedScholarName.value}.`;
  if (pub.favoriteOnly.value && pub.mode.value === "unread") return `No unread favorites for ${pub.selectedScholarName.value}.`;
  if (pub.favoriteOnly.value) return `No favorites for ${pub.selectedScholarName.value}.`;
  if (pub.mode.value === "unread") return `No unread publications for ${pub.selectedScholarName.value}.`;
  return `No publication records for ${pub.selectedScholarName.value}.`;
});
const allVisibleUnreadSelected = computed(() => {
  if (pub.visibleUnreadKeys.value.size === 0) return false;
  for (const key of pub.visibleUnreadKeys.value) {
    if (!selectedPublicationKeys.value.has(key)) return false;
  }
  return true;
});

// --- Watchers ---

watch(pub.sortedPublications, (items) => {
  const validKeys = new Set(items.filter((item) => !item.is_read).map((item) => publicationKey(item)));
  const next = new Set<string>();
  for (const key of selectedPublicationKeys.value) {
    if (validKeys.has(key)) next.add(key);
  }
  if (next.size !== selectedPublicationKeys.value.size) selectedPublicationKeys.value = next;
});

watch(hasSelection, (nextHasSelection) => {
  const validValues = new Set(bulkActionOptions.value.map((item) => item.value));
  if (validValues.has(bulkAction.value)) return;
  bulkAction.value = nextHasSelection ? "mark_selected_read" : "mark_all_unread_read";
});

// --- Filter change handlers ---

async function onModeChanged(): Promise<void> {
  pub.resetPageAndSnapshot();
  await pub.syncFiltersToRoute();
  await pub.loadPublications();
}

async function onScholarFilterChanged(): Promise<void> {
  pub.resetPageAndSnapshot();
  await pub.syncFiltersToRoute();
  await pub.loadPublications();
}

async function onFavoriteOnlyChanged(): Promise<void> {
  pub.favoriteOnly.value = !pub.favoriteOnly.value;
  pub.resetPageAndSnapshot();
  await pub.syncFiltersToRoute();
  await pub.loadPublications();
}

async function onPageSizeChanged(): Promise<void> {
  pub.resetPageAndSnapshot();
  await pub.syncFiltersToRoute();
  await pub.loadPublications();
}

async function onPrevPage(): Promise<void> {
  if (!pub.hasPrevPage.value || pub.currentPage.value <= 1) return;
  pub.currentPage.value -= 1;
  await pub.syncFiltersToRoute();
  await pub.loadPublications();
}

async function onNextPage(): Promise<void> {
  if (!pub.hasNextPage.value) return;
  pub.currentPage.value += 1;
  await pub.syncFiltersToRoute();
  await pub.loadPublications();
}

// --- Row actions ---

function canRetryPublicationPdf(item: PublicationItem): boolean {
  return !item.pdf_url && item.pdf_status === "failed" && item.pdf_attempt_count > 0;
}

async function onToggleFavorite(item: PublicationItem): Promise<void> {
  const key = publicationKey(item);
  if (favoriteUpdatingKeys.value.has(key)) return;
  const nextFavorite = !item.is_favorite;
  const nextUpdating = new Set(favoriteUpdatingKeys.value);
  nextUpdating.add(key);
  favoriteUpdatingKeys.value = nextUpdating;
  pub.errorMessage.value = null;
  pub.errorRequestId.value = null;
  pub.replacePublication({ ...item, is_favorite: nextFavorite });
  try {
    const response = await togglePublicationFavorite(item.publication_id, item.scholar_profile_id, nextFavorite);
    pub.replacePublication(response.publication);
  } catch (error) {
    pub.replacePublication({ ...item, is_favorite: item.is_favorite });
    if (error instanceof ApiRequestError) {
      pub.errorMessage.value = error.message;
      pub.errorRequestId.value = error.requestId;
    } else {
      pub.errorMessage.value = "Unable to update favorite state.";
    }
  } finally {
    const cleared = new Set(favoriteUpdatingKeys.value);
    cleared.delete(key);
    favoriteUpdatingKeys.value = cleared;
  }
}

async function onRetryPdf(item: PublicationItem): Promise<void> {
  if (item.pdf_url || !canRetryPublicationPdf(item)) return;
  const key = publicationKey(item);
  const next = new Set(retryingPublicationKeys.value);
  next.add(key);
  retryingPublicationKeys.value = next;
  pub.errorMessage.value = null;
  pub.errorRequestId.value = null;
  pub.successMessage.value = null;
  try {
    const response = await retryPublicationPdf(item.publication_id, item.scholar_profile_id);
    pub.replacePublication(response.publication);
    pub.successMessage.value = response.message;
  } catch (error) {
    if (error instanceof ApiRequestError) {
      pub.errorMessage.value = error.message;
      pub.errorRequestId.value = error.requestId;
    } else {
      pub.errorMessage.value = "Unable to retry PDF lookup for this publication.";
    }
  } finally {
    const cleared = new Set(retryingPublicationKeys.value);
    cleared.delete(key);
    retryingPublicationKeys.value = cleared;
  }
}

// --- Bulk actions ---

function onToggleAllVisible(event: Event): void {
  const checked = (event.target as HTMLInputElement).checked;
  const next = new Set(selectedPublicationKeys.value);
  for (const key of pub.visibleUnreadKeys.value) {
    if (checked) { next.add(key); } else { next.delete(key); }
  }
  selectedPublicationKeys.value = next;
}

function onToggleRowSelection(item: PublicationItem, event: Event): void {
  const checked = (event.target as HTMLInputElement).checked;
  const key = publicationKey(item);
  const next = new Set(selectedPublicationKeys.value);
  if (checked) { next.add(key); } else { next.delete(key); }
  selectedPublicationKeys.value = next;
}

async function onApplyBulkAction(): Promise<void> {
  if (bulkApplyDisabled.value) return;
  if (bulkAction.value === "select_all_visible_unread") {
    selectedPublicationKeys.value = new Set(pub.visibleUnreadKeys.value);
    return;
  }
  if (bulkAction.value === "clear_selection") { selectedPublicationKeys.value = new Set(); return; }
  if (bulkAction.value === "mark_selected_read") { await onMarkSelectedRead(); return; }
  await onMarkAllRead();
}

async function onMarkSelectedRead(): Promise<void> {
  if (selectedPublicationKeys.value.size === 0 || !pub.listState.value) return;
  const selectedLookup = new Set(selectedPublicationKeys.value);
  const selections = pub.listState.value.publications
    .filter((item) => selectedLookup.has(publicationKey(item)))
    .map((item) => ({ scholar_profile_id: item.scholar_profile_id, publication_id: item.publication_id }));
  publishingSelected.value = true;
  pub.successMessage.value = null;
  pub.errorMessage.value = null;
  pub.errorRequestId.value = null;
  try {
    const response = await markSelectedRead(selections);
    pub.successMessage.value = `${response.updated_count} publication${response.updated_count === 1 ? "" : "s"} marked as read.`;
    selectedPublicationKeys.value = new Set();
    await pub.loadPublications();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      pub.errorMessage.value = error.message;
      pub.errorRequestId.value = error.requestId;
    } else {
      pub.errorMessage.value = "Unable to mark selected publications as read.";
    }
  } finally {
    publishingSelected.value = false;
  }
}

async function onMarkAllRead(): Promise<void> {
  publishingAll.value = true;
  pub.successMessage.value = null;
  pub.errorMessage.value = null;
  pub.errorRequestId.value = null;
  try {
    const response = await markAllRead();
    pub.successMessage.value = `${response.updated_count} publication${response.updated_count === 1 ? "" : "s"} marked as read.`;
    selectedPublicationKeys.value = new Set();
    await pub.loadPublications();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      pub.errorMessage.value = error.message;
      pub.errorRequestId.value = error.requestId;
    } else {
      pub.errorMessage.value = "Unable to mark publications as read.";
    }
  } finally {
    publishingAll.value = false;
  }
}

async function onStartRun(): Promise<void> {
  if (startRunDisabled.value) return;
  pub.successMessage.value = null;
  pub.errorMessage.value = null;
  pub.errorRequestId.value = null;
  const result = await runStatus.startManualCheck();
  if (result.kind === "started") { pub.successMessage.value = `Run #${result.runId} started.`; return; }
  if (result.kind === "already_running") {
    pub.successMessage.value = result.runId ? `Run #${result.runId} is already in progress.` : "A run is already in progress.";
    return;
  }
  pub.errorMessage.value = result.message;
  pub.errorRequestId.value = result.requestId;
}

// --- Lifecycle ---

onMounted(() => {
  pub.syncFiltersFromRoute();
  startRunStatusSyncLoop();
  void Promise.all([pub.loadScholarFilters(), pub.loadPublications(), runStatus.syncLatest()]);
});

onUnmounted(() => {
  stopRunStatusSyncLoop();
});
</script>

<template>
  <AppPage
    title="Publications"
    subtitle="Review discoveries, open PDFs, and update read/favorite state in one workspace."
    fill
  >
    <div class="flex min-h-0 flex-1 flex-col gap-4 xl:overflow-hidden">
      <AppCard class="flex min-h-0 flex-1 flex-col gap-4">
      <PublicationToolbar
        :mode="pub.mode.value"
        :selected-scholar-filter="pub.selectedScholarFilter.value"
        :search-query="pub.searchQuery.value"
        :favorite-only="pub.favoriteOnly.value"
        :action-busy="actionBusy"
        :loading="pub.loading.value"
        :scholars="pub.scholars.value"
        :start-run-disabled="startRunDisabled"
        :start-run-disabled-reason="startRunDisabledReason"
        :start-run-button-label="startRunButtonLabel"
        @update:mode="pub.mode.value = $event"
        @update:selected-scholar-filter="pub.selectedScholarFilter.value = $event"
        @update:search-query="pub.searchQuery.value = $event"
        @mode-changed="onModeChanged"
        @scholar-filter-changed="onScholarFilterChanged"
        @favorite-only-changed="onFavoriteOnlyChanged"
        @reset-search="pub.searchQuery.value = ''"
        @start-run="onStartRun"
        @refresh="pub.loadPublications"
      />

      <RequestStateAlerts
        :success-message="pub.successMessage.value"
        success-title="Publication update complete"
        :error-message="pub.errorMessage.value"
        :error-request-id="pub.errorRequestId.value"
        error-title="Publication request failed"
        @dismiss-success="pub.successMessage.value = null"
      />

      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-stroke-default pt-3">
        <div class="flex items-center gap-1">
          <h3 class="text-base font-semibold text-ink-primary">Results</h3>
          <AppHelpHint text="Star to favorite, open PDF when available, and retry only after failed PDF lookup attempts." />
        </div>
        <div class="flex flex-wrap items-center justify-end gap-2 text-[11px] text-secondary">
          <span>Scope: {{ scopeLabel }} | Showing {{ pub.selectedScholarName.value }}</span>
          <div class="flex items-center gap-1">
            <label for="publications-page-size" class="sr-only">Page size</label>
            <AppSelect
              id="publications-page-size"
              v-model="pub.pageSize.value"
              :disabled="pub.loading.value"
              class="max-w-[8rem] !py-1.5 !text-xs"
              @change="onPageSizeChanged"
            >
              <option value="25">25 / page</option>
              <option value="50">50 / page</option>
              <option value="100">100 / page</option>
              <option value="200">200 / page</option>
            </AppSelect>
            <AppHelpHint text="When no rows are selected, actions target all unread results. After selecting rows, the menu switches to selected-row actions." />
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
        :loading="pub.loading.value"
        :loading-lines="8"
        :empty="showingEmptyList"
        :empty-title="emptyTitle"
        :empty-body="emptyBody"
        :show-empty="!pub.errorMessage.value"
      >
        <AppTable v-if="pub.listState.value" label="Publication list table">
          <thead>
            <tr>
              <th scope="col" class="w-10">
                <input
                  type="checkbox"
                  class="h-4 w-4 rounded border-stroke-interactive bg-surface-input text-brand-600 focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset"
                  :checked="allVisibleUnreadSelected"
                  :disabled="pub.visibleUnreadKeys.value.size === 0"
                  aria-label="Select all visible unread publications"
                  @change="onToggleAllVisible"
                />
              </th>
              <th scope="col" class="w-12 text-left font-semibold text-ink-primary">★</th>
              <th scope="col" class="w-[44%] min-w-[24rem]">
                <button type="button" class="table-sort" @click="pub.toggleSort('title')">
                  Title <span aria-hidden="true" class="sort-marker">{{ pub.sortMarker('title') }}</span>
                </button>
              </th>
              <th scope="col" class="w-[16%] min-w-[12rem]">
                <button type="button" class="table-sort" @click="pub.toggleSort('scholar')">
                  Scholar <span aria-hidden="true" class="sort-marker">{{ pub.sortMarker('scholar') }}</span>
                </button>
              </th>
              <th scope="col" class="w-[8.5rem] whitespace-nowrap">
                <button type="button" class="table-sort" @click="pub.toggleSort('pdf_status')">
                  PDF <span aria-hidden="true" class="sort-marker">{{ pub.sortMarker('pdf_status') }}</span>
                </button>
              </th>
              <th scope="col" class="w-16 whitespace-nowrap">
                <button type="button" class="table-sort" @click="pub.toggleSort('year')">
                  Year <span aria-hidden="true" class="sort-marker">{{ pub.sortMarker('year') }}</span>
                </button>
              </th>
              <th scope="col" class="w-24 whitespace-nowrap">
                <button type="button" class="table-sort" @click="pub.toggleSort('citations')">
                  Citations <span aria-hidden="true" class="sort-marker">{{ pub.sortMarker('citations') }}</span>
                </button>
              </th>
              <th scope="col" class="w-44 whitespace-nowrap text-left font-semibold text-ink-primary">Read status</th>
              <th scope="col" class="w-32 whitespace-nowrap">
                <button type="button" class="table-sort" @click="pub.toggleSort('first_seen')">
                  First seen <span aria-hidden="true" class="sort-marker">{{ pub.sortMarker('first_seen') }}</span>
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            <PublicationTableRow
              v-for="item in pub.sortedPublications.value"
              :key="publicationKey(item)"
              :item="item"
              :item-key="publicationKey(item)"
              :selected="selectedPublicationKeys.has(publicationKey(item))"
              :favorite-updating="favoriteUpdatingKeys.has(publicationKey(item))"
              :retrying="retryingPublicationKeys.has(publicationKey(item))"
              :can-retry="canRetryPublicationPdf(item)"
              @toggle-selection="onToggleRowSelection(item, $event)"
              @toggle-favorite="onToggleFavorite(item)"
              @retry-pdf="onRetryPdf(item)"
            />
          </tbody>
        </AppTable>
      </AsyncStateGate>

      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-stroke-default pt-2 text-xs text-secondary">
        <span>
          total {{ pub.totalCount.value }} · visible {{ pub.visibleCount.value }} · unread {{ pub.visibleUnreadCount.value }} · favorites {{ pub.visibleFavoriteCount.value }}
          · selected {{ selectedCount }}
        </span>
        <div class="flex items-center gap-2">
          <span>page {{ pub.currentPage.value }} / {{ pub.totalPages.value }}</span>
          <AppButton variant="ghost" class="h-8 min-h-8 px-2" :disabled="!pub.hasPrevPage.value || pub.loading.value" @click="onPrevPage">
            Prev
          </AppButton>
          <AppButton variant="ghost" class="h-8 min-h-8 px-2" :disabled="!pub.hasNextPage.value || pub.loading.value" @click="onNextPage">
            Next
          </AppButton>
        </div>
      </div>
    </AppCard>
    </div>
  </AppPage>
</template>

<style scoped>
.table-sort {
  @apply flex w-full items-center justify-between gap-2 text-left font-semibold text-ink-primary transition hover:text-ink-link focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset;
}

.sort-marker {
  @apply text-[11px] leading-none text-ink-muted;
}
</style>
