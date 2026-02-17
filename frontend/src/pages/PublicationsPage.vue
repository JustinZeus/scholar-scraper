<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppPage from "@/components/layout/AppPage.vue";
import AppAlert from "@/components/ui/AppAlert.vue";
import AppBadge from "@/components/ui/AppBadge.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppEmptyState from "@/components/ui/AppEmptyState.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppSelect from "@/components/ui/AppSelect.vue";
import AppSkeleton from "@/components/ui/AppSkeleton.vue";
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

const loading = ref(true);
const publishingAll = ref(false);
const publishingSelected = ref(false);
const mode = ref<PublicationMode>("new");
const selectedScholarFilter = ref("");
const searchQuery = ref("");

const scholars = ref<ScholarProfile[]>([]);
const listState = ref<PublicationsResult | null>(null);
const selectedPublicationKeys = ref<Set<string>>(new Set());

const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);
const route = useRoute();
const router = useRouter();

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

const visibleUnreadKeys = computed(() => {
  const keys = new Set<string>();
  for (const item of filteredPublications.value) {
    if (!item.is_read) {
      keys.add(publicationKey(item));
    }
  }
  return keys;
});

const selectedCount = computed(() => selectedPublicationKeys.value.size);

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

watch(filteredPublications, (items) => {
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
    successMessage.value = response.message;
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
  <AppPage title="Publications" subtitle="Filter, search, and triage publication status quickly.">
    <div class="grid gap-3 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
      <div class="grid gap-3 md:grid-cols-[auto_auto_minmax(0,1fr)] md:items-end">
        <div class="grid gap-1 text-xs text-secondary">
          <span>Scope</span>
          <div class="flex min-h-10 flex-wrap items-center gap-2">
            <AppButton :variant="mode === 'new' ? 'primary' : 'secondary'" @click="setMode('new')">
              New
            </AppButton>
            <AppButton :variant="mode === 'all' ? 'primary' : 'secondary'" @click="setMode('all')">
              All
            </AppButton>
          </div>
        </div>

        <label class="grid gap-1 text-xs text-secondary" for="publications-scholar-filter">
          <span>Scholar</span>
          <AppSelect
            id="publications-scholar-filter"
            v-model="selectedScholarFilter"
            :disabled="loading || publishingAll || publishingSelected"
            @change="onScholarFilterChanged"
          >
            <option value="">All scholars</option>
            <option v-for="scholar in scholars" :key="scholar.id" :value="String(scholar.id)">
              {{ scholar.display_name || scholar.scholar_id }}
            </option>
          </AppSelect>
        </label>

        <label class="grid gap-1 text-xs text-secondary" for="publications-search-input">
          <span>Search</span>
          <AppInput
            id="publications-search-input"
            v-model="searchQuery"
            placeholder="Search title, scholar, venue, year"
            :disabled="loading"
          />
        </label>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <AppButton
          variant="secondary"
          :disabled="selectedCount === 0 || loading || publishingSelected || publishingAll"
          @click="onMarkSelectedRead"
        >
          {{ publishingSelected ? "Marking..." : `Mark selected read (${selectedCount})` }}
        </AppButton>
        <AppButton variant="secondary" :disabled="publishingAll || loading || publishingSelected" @click="onMarkAllRead">
          {{ publishingAll ? "Marking..." : "Mark all unread as read" }}
        </AppButton>
        <AppButton variant="ghost" :disabled="loading" @click="loadPublications">
          {{ loading ? "Refreshing..." : "Refresh" }}
        </AppButton>
      </div>
    </div>

    <AppAlert v-if="successMessage" tone="success" dismissible @dismiss="successMessage = null">
      <template #title>Update complete</template>
      <p>{{ successMessage }}</p>
    </AppAlert>

    <AppAlert v-if="errorMessage" tone="danger">
      <template #title>Publication request failed</template>
      <p>{{ errorMessage }}</p>
      <p class="text-secondary">Request ID: {{ errorRequestId || "n/a" }}</p>
    </AppAlert>

    <AppSkeleton v-if="loading" :lines="8" />

    <template v-else-if="listState">
      <AppCard class="space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Publication list</h2>
          <div class="flex flex-wrap items-center gap-2">
            <AppBadge tone="info">Mode: {{ listState.mode }}</AppBadge>
            <AppBadge tone="neutral">Visible: {{ filteredPublications.length }}</AppBadge>
          </div>
        </div>

        <AppEmptyState
          v-if="filteredPublications.length === 0"
          title="No publications found"
          body="Try changing mode, scholar filter, or search terms."
        />

        <AppTable v-else label="Publication list table">
          <thead>
            <tr>
              <th scope="col" class="w-12">
                <input
                  type="checkbox"
                  class="h-4 w-4 rounded border-zinc-400 text-brand-600 focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-100 dark:border-zinc-600 dark:bg-zinc-900 dark:focus-visible:ring-brand-400 dark:focus-visible:ring-offset-zinc-950"
                  :checked="allVisibleUnreadSelected"
                  :disabled="visibleUnreadKeys.size === 0"
                  aria-label="Select all visible unread publications"
                  @change="onToggleAllVisible"
                />
              </th>
              <th scope="col">Title</th>
              <th scope="col">Scholar</th>
              <th scope="col">Year</th>
              <th scope="col">Citations</th>
              <th scope="col">Status</th>
              <th scope="col">First seen</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in filteredPublications" :key="publicationKey(item)">
              <td>
                <input
                  type="checkbox"
                  class="h-4 w-4 rounded border-zinc-400 text-brand-600 focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-100 dark:border-zinc-600 dark:bg-zinc-900 dark:focus-visible:ring-brand-400 dark:focus-visible:ring-offset-zinc-950"
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
                    {{ item.is_new_in_latest_run ? "New" : "Existing" }}
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
      </AppCard>
    </template>
  </AppPage>
</template>
