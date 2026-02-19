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
import AppSelect from "@/components/ui/AppSelect.vue";
import AppTable from "@/components/ui/AppTable.vue";
import {
  listPublications,
  markAllRead,
  markSelectedRead,
  type PublicationItem,
  type PublicationMode,
  type PublicationsResult,
} from "@/features/publications";
import { listScholars, type ScholarProfile } from "@/features/scholars";
import { ApiRequestError } from "@/lib/api/errors";

type PublicationSortKey = "title" | "scholar" | "year" | "citations" | "status" | "first_seen";

const loading = ref(true);
const publishingAll = ref(false);
const publishingSelected = ref(false);
const mode = ref<PublicationMode>("all");
const selectedScholarFilter = ref("");
const searchQuery = ref("");
const sortKey = ref<PublicationSortKey>("first_seen");
const sortDirection = ref<"asc" | "desc">("desc");

const scholars = ref<ScholarProfile[]>([]);
const listState = ref<PublicationsResult | null>(null);
const selectedPublicationKeys = ref<Set<string>>(new Set());

const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);
const route = useRoute();
const router = useRouter();
const textCollator = new Intl.Collator(undefined, { sensitivity: "base", numeric: true });

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

function syncScholarFilterFromRoute(): boolean {
  const nextValue = normalizeScholarFilterQuery(route.query.scholar);
  if (selectedScholarFilter.value === nextValue) {
    return false;
  }

  selectedScholarFilter.value = nextValue;
  return true;
}

async function syncScholarFilterToRoute(): Promise<void> {
  const nextValue = selectedScholarFilter.value.trim();
  const currentValue = normalizeScholarFilterQuery(route.query.scholar);
  if (nextValue === currentValue) {
    return;
  }

  const nextQuery = {
    ...route.query,
    scholar: nextValue || undefined,
  };

  await router.replace({ query: nextQuery });
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

const selectedCount = computed(() => selectedPublicationKeys.value.size);
const visibleCount = computed(() => sortedPublications.value.length);
const visibleUnreadCount = computed(() => visibleUnreadKeys.value.size);
const actionBusy = computed(() => loading.value || publishingAll.value || publishingSelected.value);
const showingEmptyList = computed(() => Boolean(listState.value) && sortedPublications.value.length === 0);
const modeLabel = computed(() => (mode.value === "unread" ? "Unread" : "All records"));

const emptyTitle = computed(() =>
  searchQuery.value.trim().length > 0 ? "No publications match this search" : "No publications found",
);

const emptyBody = computed(() => {
  if (searchQuery.value.trim().length > 0) {
    return "Try another title, scholar, venue, or year.";
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
      scholarProfileId: selectedScholarId(),
      limit: 400,
    });
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

async function setMode(nextMode: PublicationMode): Promise<void> {
  if (mode.value === nextMode) {
    return;
  }
  mode.value = nextMode;
  await loadPublications();
}

async function onScholarFilterChanged(): Promise<void> {
  await syncScholarFilterToRoute();
  await loadPublications();
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

function resetSearchQuery(): void {
  searchQuery.value = "";
}

onMounted(() => {
  syncScholarFilterFromRoute();
  void Promise.all([loadScholarFilters(), loadPublications()]);
});

watch(
  () => route.query.scholar,
  async () => {
    const changed = syncScholarFilterFromRoute();
    if (!changed) {
      return;
    }
    await loadPublications();
  },
);
</script>

<template>
  <AppPage
    title="Publications"
    subtitle="Filter discovered publications, then mark what you have read so upcoming checks stay focused."
  >
    <AppCard class="space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="space-y-1">
          <div class="flex items-center gap-1">
            <h2 class="text-lg font-semibold text-ink-primary">What you can do here</h2>
            <AppHelpHint
              text="Publications are records discovered from tracked scholar profiles. Unread mode focuses only on items you have not marked as read."
            />
          </div>
          <p class="text-sm text-secondary">
            Select a scholar or scope, search within results, and mark items as read when you are done.
          </p>
        </div>

        <AppButton variant="ghost" :disabled="loading" @click="loadPublications">
          {{ loading ? "Refreshing..." : "Refresh" }}
        </AppButton>
      </div>

      <div class="grid gap-3 xl:grid-cols-[minmax(0,15rem)_minmax(0,18rem)_minmax(0,1fr)] xl:items-end">
        <div class="grid gap-1 text-xs text-secondary">
          <span>View mode</span>
          <div class="flex min-h-10 flex-wrap items-center gap-2">
            <AppButton
              :variant="mode === 'unread' ? 'primary' : 'secondary'"
              class="min-w-16 justify-center"
              :disabled="actionBusy"
              @click="setMode('unread')"
            >
              Unread
            </AppButton>
            <AppButton
              :variant="mode === 'all' ? 'primary' : 'secondary'"
              class="min-w-16 justify-center"
              :disabled="actionBusy"
              @click="setMode('all')"
            >
              All records
            </AppButton>
          </div>
        </div>

        <label class="grid gap-1 text-xs text-secondary" for="publications-scholar-filter">
          <span>Scholar</span>
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
          <span>Search within current scope</span>
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
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-stroke-default pt-3">
        <div class="flex flex-wrap items-center gap-2">
          <AppBadge tone="info">Mode: {{ modeLabel }}</AppBadge>
          <AppBadge tone="neutral">Visible: {{ visibleCount }}</AppBadge>
          <AppBadge tone="warning">Unread: {{ visibleUnreadCount }}</AppBadge>
          <AppBadge tone="success">Selected: {{ selectedCount }}</AppBadge>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <AppButton
            variant="secondary"
            :disabled="selectedCount === 0 || actionBusy"
            @click="onMarkSelectedRead"
          >
            {{ publishingSelected ? "Updating..." : `Mark selected as read (${selectedCount})` }}
          </AppButton>
          <AppButton variant="secondary" :disabled="actionBusy || visibleUnreadCount === 0" @click="onMarkAllRead">
            {{ publishingAll ? "Updating..." : "Mark all unread as read" }}
          </AppButton>
        </div>
      </div>
    </AppCard>

    <RequestStateAlerts
      :success-message="successMessage"
      success-title="Publication update complete"
      :error-message="errorMessage"
      :error-request-id="errorRequestId"
      error-title="Publication request failed"
      @dismiss-success="successMessage = null"
    />

    <AppCard class="space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-1">
          <h2 class="text-lg font-semibold text-ink-primary">Publication List</h2>
          <AppHelpHint
            text="Use sorting, search, and bulk actions here to move discovered records from unread into read history."
          />
        </div>
        <span class="text-xs text-secondary">Currently showing {{ selectedScholarName }}</span>
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
              <th scope="col" class="w-12">
                <input
                  type="checkbox"
                  class="h-4 w-4 rounded border-stroke-interactive bg-surface-input text-brand-600 focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset"
                  :checked="allVisibleUnreadSelected"
                  :disabled="visibleUnreadKeys.size === 0"
                  aria-label="Select all visible unread publications"
                  @change="onToggleAllVisible"
                />
              </th>
              <th scope="col">
                <button type="button" class="table-sort" @click="toggleSort('title')">
                  Title <span aria-hidden="true">{{ sortMarker("title") }}</span>
                </button>
              </th>
              <th scope="col">
                <button type="button" class="table-sort" @click="toggleSort('scholar')">
                  Scholar <span aria-hidden="true">{{ sortMarker("scholar") }}</span>
                </button>
              </th>
              <th scope="col">
                <button type="button" class="table-sort" @click="toggleSort('year')">
                  Year <span aria-hidden="true">{{ sortMarker("year") }}</span>
                </button>
              </th>
              <th scope="col">
                <button type="button" class="table-sort" @click="toggleSort('citations')">
                  Citations <span aria-hidden="true">{{ sortMarker("citations") }}</span>
                </button>
              </th>
              <th scope="col">
                <button type="button" class="table-sort" @click="toggleSort('status')">
                  Read status <span aria-hidden="true">{{ sortMarker("status") }}</span>
                </button>
              </th>
              <th scope="col">
                <button type="button" class="table-sort" @click="toggleSort('first_seen')">
                  First seen <span aria-hidden="true">{{ sortMarker("first_seen") }}</span>
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
                <a
                  v-if="item.pub_url"
                  :href="item.pub_url"
                  target="_blank"
                  rel="noreferrer"
                  class="link-inline"
                >
                  {{ item.title }}
                </a>
                <span v-else>{{ item.title }}</span>
              </td>
              <td>{{ item.scholar_label }}</td>
              <td>{{ item.year ?? "n/a" }}</td>
              <td>{{ item.citation_count }}</td>
              <td>
                <div class="flex flex-wrap items-center gap-2">
                  <AppBadge :tone="item.is_new_in_latest_run ? 'info' : 'neutral'">
                    {{ item.is_new_in_latest_run ? "New this check" : "Seen before" }}
                  </AppBadge>
                  <AppBadge :tone="item.is_read ? 'success' : 'warning'">
                    {{ item.is_read ? "Read" : "Unread" }}
                  </AppBadge>
                </div>
              </td>
              <td>{{ formatDate(item.first_seen_at) }}</td>
            </tr>
          </tbody>
        </AppTable>
      </AsyncStateGate>
    </AppCard>
  </AppPage>
</template>

<style scoped>
.table-sort {
  @apply inline-flex items-center gap-1 text-left font-semibold text-ink-primary transition hover:text-ink-link focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset;
}
</style>
