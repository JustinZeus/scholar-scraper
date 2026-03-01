<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import AppPage from "@/components/layout/AppPage.vue";
import AsyncStateGate from "@/components/patterns/AsyncStateGate.vue";
import RequestStateAlerts from "@/components/patterns/RequestStateAlerts.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppEmptyState from "@/components/ui/AppEmptyState.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppRefreshButton from "@/components/ui/AppRefreshButton.vue";
import AppSelect from "@/components/ui/AppSelect.vue";
import AppTable from "@/components/ui/AppTable.vue";
import {
  clearScholarImage,
  createScholar,
  deleteScholar,
  exportScholarData,
  importScholarData,
  listScholars,
  setScholarImageUrl,
  toggleScholar,
  uploadScholarImage,
  type DataImportPayload,
  type DataImportResult,
  type ScholarProfile,
  type ScholarSearchCandidate,
} from "@/features/scholars";
import ScholarAvatar from "@/features/scholars/components/ScholarAvatar.vue";
import ScholarBatchAdd from "@/features/scholars/components/ScholarBatchAdd.vue";
import ScholarNameSearch from "@/features/scholars/components/ScholarNameSearch.vue";
import ScholarSettingsModal from "@/features/scholars/components/ScholarSettingsModal.vue";
import { ApiRequestError } from "@/lib/api/errors";
import { useRunStatusStore } from "@/stores/run_status";

const loading = ref(true);
const saving = ref(false);
const activeScholarId = ref<number | null>(null);
const imageSavingScholarId = ref<number | null>(null);
const imageUploadingScholarId = ref<number | null>(null);
const addingCandidateScholarId = ref<string | null>(null);
const activeScholarSettingsId = ref<number | null>(null);
const importingData = ref(false);
const exportingData = ref(false);
const importFileInput = ref<HTMLInputElement | null>(null);

const scholars = ref<ScholarProfile[]>([]);
const imageUrlDraftByScholarId = ref<Record<number, string>>({});
const trackedFilterQuery = ref("");
type TrackedScholarSort = "recent" | "name_asc" | "name_desc" | "enabled_first";
const trackedSort = ref<TrackedScholarSort>("recent");

const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);

const SCHOLARS_LIVE_SYNC_INTERVAL_MS = 4000;
let scholarsLiveSyncTimer: ReturnType<typeof setInterval> | null = null;
const runStatus = useRunStatusStore();

// --- Helpers ---

function scholarLabel(profile: ScholarProfile): string {
  return profile.display_name || profile.scholar_id;
}

function scholarProfileUrl(scholarId: string): string {
  return `https://scholar.google.com/citations?hl=en&user=${encodeURIComponent(scholarId)}`;
}

function scholarPublicationsRoute(profile: ScholarProfile): { name: string; query: { scholar: string } } {
  return { name: "publications", query: { scholar: String(profile.id) } };
}

function isImageBusy(scholarProfileId: number): boolean {
  return imageSavingScholarId.value === scholarProfileId
    || imageUploadingScholarId.value === scholarProfileId
    || activeScholarId.value === scholarProfileId;
}

// --- Scholar list management ---

const trackedScholarIds = computed(() => new Set(scholars.value.map((item) => item.scholar_id)));
const activeScholarSettings = computed(
  () => scholars.value.find((item) => item.id === activeScholarSettingsId.value) ?? null,
);
const hasTrackedScholars = computed(() => scholars.value.length > 0);

const normalizedTrackedFilter = computed(() => trackedFilterQuery.value.trim().toLocaleLowerCase());
const visibleScholars = computed(() => {
  const filter = normalizedTrackedFilter.value;
  const filtered = scholars.value.filter((item) => {
    if (!filter) return true;
    return scholarLabel(item).toLocaleLowerCase().includes(filter)
      || item.scholar_id.toLocaleLowerCase().includes(filter);
  });
  const byName = (a: ScholarProfile, b: ScholarProfile) =>
    scholarLabel(a).localeCompare(scholarLabel(b), undefined, { sensitivity: "base" });
  const sorted = [...filtered];
  if (trackedSort.value === "name_asc") { sorted.sort(byName); return sorted; }
  if (trackedSort.value === "name_desc") { sorted.sort((a, b) => byName(b, a)); return sorted; }
  if (trackedSort.value === "enabled_first") {
    sorted.sort((a, b) => {
      if (a.is_enabled !== b.is_enabled) return a.is_enabled ? -1 : 1;
      return byName(a, b);
    });
    return sorted;
  }
  sorted.sort((a, b) => b.id - a.id);
  return sorted;
});
const hasVisibleScholars = computed(() => visibleScholars.value.length > 0);
const trackedCountLabel = computed(() => {
  if (!normalizedTrackedFilter.value) return `${scholars.value.length} tracked`;
  return `${visibleScholars.value.length} of ${scholars.value.length}`;
});

// --- Image draft sync ---

function syncImageDrafts(): void {
  const next: Record<number, string> = {};
  for (const item of scholars.value) {
    const existing = imageUrlDraftByScholarId.value[item.id];
    if (typeof existing === "string" && existing.length > 0) { next[item.id] = existing; continue; }
    next[item.id] = item.profile_image_source === "override" ? (item.profile_image_url ?? "") : "";
  }
  imageUrlDraftByScholarId.value = next;
}

function applyScholarList(nextScholars: ScholarProfile[]): void {
  scholars.value = nextScholars;
  syncImageDrafts();
}

function upsertScholar(profile: ScholarProfile): void {
  const existingIndex = scholars.value.findIndex((item) => item.id === profile.id);
  if (existingIndex < 0) { applyScholarList([profile, ...scholars.value]); return; }
  const next = [...scholars.value];
  next[existingIndex] = profile;
  applyScholarList(next);
}

// --- Live sync ---

function stopScholarLiveSync(): void {
  if (scholarsLiveSyncTimer === null) return;
  clearInterval(scholarsLiveSyncTimer);
  scholarsLiveSyncTimer = null;
}

function startScholarLiveSync(): void {
  if (scholarsLiveSyncTimer !== null) return;
  scholarsLiveSyncTimer = setInterval(() => { void refreshScholarsSilently(); }, SCHOLARS_LIVE_SYNC_INTERVAL_MS);
}

async function refreshScholarsSilently(): Promise<void> {
  try { applyScholarList(await listScholars()); } catch { /* Keep existing list. */ }
}

// --- Data loading ---

async function loadScholars(): Promise<void> {
  loading.value = true;
  try {
    applyScholarList(await listScholars());
  } catch (error) {
    applyScholarList([]);
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to load scholars.";
    }
  } finally {
    loading.value = false;
  }
}

// --- Actions ---

function assignError(error: unknown, fallback: string): void {
  if (error instanceof ApiRequestError) {
    errorMessage.value = error.message;
    errorRequestId.value = error.requestId;
  } else if (error instanceof Error) {
    errorMessage.value = error.message;
  } else {
    errorMessage.value = fallback;
  }
}

function clearMessages(): void {
  errorMessage.value = null;
  errorRequestId.value = null;
  successMessage.value = null;
}

async function onAddScholars(scholarIds: string[]): Promise<void> {
  saving.value = true;
  clearMessages();
  try {
    const settled = await Promise.allSettled(
      scholarIds.map(async (scholarId) => {
        const created = await createScholar({ scholar_id: scholarId });
        upsertScholar(created);
        return created;
      }),
    );
    const failures: string[] = [];
    let requestIdFromFailures: string | null = null;
    let createdCount = 0;
    settled.forEach((result, index) => {
      if (result.status === "fulfilled") { createdCount += 1; return; }
      const scholarId = scholarIds[index];
      if (result.reason instanceof ApiRequestError) {
        failures.push(`${scholarId}: ${result.reason.message}`);
        if (!requestIdFromFailures && result.reason.requestId) requestIdFromFailures = result.reason.requestId;
      } else if (result.reason instanceof Error) {
        failures.push(`${scholarId}: ${result.reason.message}`);
      } else {
        failures.push(`${scholarId}: Unable to create scholar.`);
      }
    });
    if (createdCount > 0) {
      const total = scholarIds.length;
      successMessage.value = `Added ${createdCount} of ${total} scholar${total === 1 ? "" : "s"}.`;
    }
    if (failures.length > 0) {
      const preview = failures.slice(0, 3).join(" | ");
      const remainder = failures.length > 3 ? ` (+${failures.length - 3} more)` : "";
      errorMessage.value = `Failed to add ${failures.length} scholar${failures.length === 1 ? "" : "s"}: ${preview}${remainder}`;
      errorRequestId.value = requestIdFromFailures;
    }
    await refreshScholarsSilently();
  } catch (error) {
    assignError(error, "Unable to create scholar records.");
  } finally {
    saving.value = false;
  }
}

async function onAddCandidate(candidate: ScholarSearchCandidate): Promise<void> {
  addingCandidateScholarId.value = candidate.scholar_id;
  clearMessages();
  try {
    const created = await createScholar({ scholar_id: candidate.scholar_id, profile_image_url: candidate.profile_image_url ?? undefined });
    upsertScholar(created);
    successMessage.value = `${candidate.display_name} added.`;
  } catch (error) {
    assignError(error, "Unable to add scholar from search result.");
  } finally {
    addingCandidateScholarId.value = null;
  }
}

async function onToggleScholar(): Promise<void> {
  const profile = activeScholarSettings.value;
  if (!profile) return;
  activeScholarId.value = profile.id;
  clearMessages();
  try {
    await toggleScholar(profile.id);
    successMessage.value = `${scholarLabel(profile)} ${profile.is_enabled ? "disabled" : "enabled"}.`;
    await loadScholars();
  } catch (error) {
    assignError(error, "Unable to update scholar status.");
  } finally {
    activeScholarId.value = null;
  }
}

async function onDeleteScholar(): Promise<void> {
  const profile = activeScholarSettings.value;
  if (!profile) return;
  const label = scholarLabel(profile);
  if (!window.confirm(`Delete scholar ${label}? This removes all linked publications and queue data.`)) return;
  activeScholarId.value = profile.id;
  clearMessages();
  try {
    await deleteScholar(profile.id);
    successMessage.value = `${label} deleted.`;
    activeScholarSettingsId.value = null;
    await loadScholars();
  } catch (error) {
    assignError(error, "Unable to delete scholar.");
  } finally {
    activeScholarId.value = null;
  }
}

async function onSaveImageUrl(): Promise<void> {
  const profile = activeScholarSettings.value;
  if (!profile) return;
  const candidate = (imageUrlDraftByScholarId.value[profile.id] || "").trim();
  if (!candidate) { errorMessage.value = "Enter an image URL before saving, or use Reset image."; return; }
  imageSavingScholarId.value = profile.id;
  clearMessages();
  try {
    await setScholarImageUrl(profile.id, candidate);
    successMessage.value = `Image URL updated for ${scholarLabel(profile)}.`;
    await loadScholars();
  } catch (error) {
    assignError(error, "Unable to update scholar image URL.");
  } finally {
    imageSavingScholarId.value = null;
  }
}

async function onUploadImage(event: Event): Promise<void> {
  const profile = activeScholarSettings.value;
  if (!profile) return;
  const input = event.target as HTMLInputElement | null;
  const file = input?.files?.[0] ?? null;
  if (!file) return;
  imageUploadingScholarId.value = profile.id;
  clearMessages();
  try {
    await uploadScholarImage(profile.id, file);
    successMessage.value = `Uploaded image for ${scholarLabel(profile)}.`;
    await loadScholars();
  } catch (error) {
    assignError(error, "Unable to upload scholar image.");
  } finally {
    imageUploadingScholarId.value = null;
    if (input) input.value = "";
  }
}

async function onResetImage(): Promise<void> {
  const profile = activeScholarSettings.value;
  if (!profile) return;
  imageSavingScholarId.value = profile.id;
  clearMessages();
  try {
    await clearScholarImage(profile.id);
    successMessage.value = `Image reset for ${scholarLabel(profile)}.`;
    await loadScholars();
  } catch (error) {
    assignError(error, "Unable to reset scholar image.");
  } finally {
    imageSavingScholarId.value = null;
  }
}

// --- Import/export ---

function suggestExportFilename(exportedAt: string): string {
  return `scholarr-export-${exportedAt.slice(0, 10) || "unknown-date"}.json`;
}

function downloadJsonFile(filename: string, payload: unknown): void {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function importSummary(result: DataImportResult): string {
  return (
    `Import complete. Scholars +${result.scholars_created}` +
    ` / updated ${result.scholars_updated}; publications +${result.publications_created}` +
    ` / updated ${result.publications_updated}; links +${result.links_created}` +
    ` / updated ${result.links_updated}; skipped ${result.skipped_records}.`
  );
}

async function onExportData(): Promise<void> {
  exportingData.value = true;
  clearMessages();
  try {
    const payload = await exportScholarData();
    downloadJsonFile(suggestExportFilename(payload.exported_at), payload);
    successMessage.value = "Export complete.";
  } catch (error) {
    assignError(error, "Unable to export scholars and publications.");
  } finally {
    exportingData.value = false;
  }
}

function onOpenImportPicker(): void {
  importFileInput.value?.click();
}

async function onImportFileSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement | null;
  const file = input?.files?.[0] ?? null;
  if (!file) return;
  importingData.value = true;
  clearMessages();
  try {
    const raw = await file.text();
    let parsed = JSON.parse(raw);
    // Accept the full export envelope (with data/meta wrapper)
    if (parsed?.data && Array.isArray(parsed.data.scholars)) {
      parsed = parsed.data;
    }
    const payload = parsed as DataImportPayload;
    if (!payload || !Array.isArray(payload.scholars) || !Array.isArray(payload.publications)) {
      throw new Error("Invalid import file: expected scholars[] and publications[] arrays.");
    }
    const result = await importScholarData(payload);
    successMessage.value = importSummary(result);
    await loadScholars();
  } catch (error) {
    assignError(error, "Unable to import scholars and publications.");
  } finally {
    importingData.value = false;
    if (input) input.value = "";
  }
}

// --- Lifecycle ---

onMounted(() => { void loadScholars(); });
onUnmounted(() => { stopScholarLiveSync(); });

watch(
  () => runStatus.isLikelyRunning,
  (isRunning) => { if (isRunning) { startScholarLiveSync(); } else { stopScholarLiveSync(); } },
  { immediate: true },
);
</script>

<template>
  <AppPage
    title="Scholars"
    subtitle="Add and maintain the Google Scholar profiles you want Scholarr to monitor."
    fill
  >
    <div class="flex min-h-0 flex-1 flex-col gap-4 xl:overflow-hidden">
      <RequestStateAlerts
        :success-message="successMessage"
        success-title="Scholar update complete"
        :error-message="errorMessage"
        :error-request-id="errorRequestId"
        error-title="Scholar request failed"
        @dismiss-success="successMessage = null"
      />

      <section class="grid min-h-0 flex-1 gap-4 xl:h-full xl:grid-cols-2 xl:grid-rows-[minmax(0,1fr)] xl:overflow-hidden">
        <div class="grid content-start gap-4 xl:order-2 xl:h-full xl:min-h-0 xl:grid-rows-[minmax(0,1fr)_minmax(0,1fr)] xl:overflow-hidden">
          <ScholarBatchAdd :saving="saving" :loading="loading" @add-scholars="onAddScholars" />
          <ScholarNameSearch
            :tracked-scholar-ids="trackedScholarIds"
            :adding-candidate-scholar-id="addingCandidateScholarId"
            @add-candidate="onAddCandidate"
          />
        </div>

        <AppCard class="flex min-h-0 flex-col gap-4 xl:order-1 xl:h-full xl:overflow-hidden">
          <div class="space-y-3">
            <div class="space-y-1">
              <div class="flex items-center gap-1">
                <h2 class="text-lg font-semibold text-ink-primary">Tracked Scholars</h2>
                <AppHelpHint text="Tracked scholars are active profile sources. Open Manage to control status, image overrides, and removal." />
              </div>
              <p class="text-sm text-secondary">Review tracked profiles, filter quickly, and open per-scholar settings when needed.</p>
            </div>
            <div class="grid gap-3 rounded-xl border border-stroke-default bg-surface-card-muted/70 px-3 py-2">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <p class="text-xs font-medium uppercase tracking-wide text-secondary">Tracking status</p>
                <div class="flex flex-wrap items-center gap-2">
                  <span class="inline-flex min-h-10 items-center rounded-lg border border-state-info-border bg-state-info-bg px-3 text-sm font-semibold text-state-info-text">
                    {{ trackedCountLabel }}
                  </span>
                  <AppButton variant="secondary" :disabled="loading || exportingData" @click="onExportData">
                    {{ exportingData ? "Exporting..." : "Export" }}
                  </AppButton>
                  <AppButton variant="secondary" :disabled="loading || importingData" @click="onOpenImportPicker">
                    {{ importingData ? "Importing..." : "Import" }}
                  </AppButton>
                  <AppRefreshButton variant="secondary" :disabled="saving" :loading="loading" title="Refresh scholars" loading-title="Refreshing scholars" @click="loadScholars" />
                </div>
              </div>
              <input ref="importFileInput" type="file" class="sr-only" accept=".json,application/json" @change="onImportFileSelected" />
              <div class="grid gap-2 sm:grid-cols-[minmax(0,1fr)_12rem]">
                <label class="grid gap-1 text-xs font-medium uppercase tracking-wide text-secondary" for="tracked-scholar-filter">
                  <span>Filter tracked scholars</span>
                  <AppInput id="tracked-scholar-filter" v-model="trackedFilterQuery" placeholder="Filter by name or scholar ID" />
                </label>
                <label class="grid gap-1 text-xs font-medium uppercase tracking-wide text-secondary" for="tracked-scholar-sort">
                  <span>Sort</span>
                  <AppSelect id="tracked-scholar-sort" v-model="trackedSort">
                    <option value="recent">Recently added</option>
                    <option value="name_asc">Name (A-Z)</option>
                    <option value="name_desc">Name (Z-A)</option>
                    <option value="enabled_first">Enabled first</option>
                  </AppSelect>
                </label>
              </div>
            </div>
          </div>

          <div class="min-h-0 flex-1 xl:overflow-hidden">
            <AsyncStateGate :loading="loading" :loading-lines="6" :empty="!hasTrackedScholars" :show-empty="!errorMessage" empty-title="No scholars tracked" empty-body="Add a Scholar ID or URL to start ingestion tracking.">
              <AppEmptyState v-if="!hasVisibleScholars" title="No scholars match this filter" body="Clear or adjust the filter to see tracked scholars." />
              <div v-else class="space-y-3 xl:flex xl:h-full xl:min-h-0 xl:flex-col xl:space-y-0 xl:overflow-hidden">
                <ul class="flex gap-3 overflow-x-auto p-1 lg:hidden">
                  <li v-for="item in visibleScholars" :key="item.id" class="rounded-xl border border-stroke-default bg-surface-card-muted/70 p-3">
                    <div class="flex items-start gap-3">
                      <ScholarAvatar :label="item.display_name" :scholar-id="item.scholar_id" :image-url="item.profile_image_url" />
                      <div class="min-w-0 flex-1 space-y-1">
                        <p class="truncate text-sm font-semibold text-ink-primary">{{ scholarLabel(item) }}</p>
                        <div class="flex flex-wrap items-center gap-3">
                          <RouterLink :to="scholarPublicationsRoute(item)" class="link-inline text-xs">Publications</RouterLink>
                          <a :href="scholarProfileUrl(item.scholar_id)" target="_blank" rel="noreferrer" class="link-inline text-xs">Open profile</a>
                        </div>
                      </div>
                      <AppButton variant="secondary" :disabled="saving" @click="activeScholarSettingsId = item.id">Manage</AppButton>
                    </div>
                  </li>
                </ul>
                <div class="hidden min-h-0 flex-1 overflow-hidden lg:block">
                  <AppTable class="h-full overflow-y-scroll overscroll-contain" label="Tracked scholars table">
                    <thead>
                      <tr>
                        <th scope="col">Scholar</th>
                        <th scope="col" class="w-[11rem]">Manage</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="item in visibleScholars" :key="item.id">
                        <td>
                          <div class="flex items-start gap-3">
                            <ScholarAvatar :label="item.display_name" :scholar-id="item.scholar_id" :image-url="item.profile_image_url" />
                            <div class="grid min-w-0 gap-1">
                              <strong class="truncate text-ink-primary">{{ scholarLabel(item) }}</strong>
                              <div class="flex flex-wrap items-center gap-3">
                                <RouterLink :to="scholarPublicationsRoute(item)" class="link-inline text-xs">Publications</RouterLink>
                                <a :href="scholarProfileUrl(item.scholar_id)" target="_blank" rel="noreferrer" class="link-inline text-xs">Open profile</a>
                              </div>
                            </div>
                          </div>
                        </td>
                        <td>
                          <AppButton variant="secondary" :disabled="saving" @click="activeScholarSettingsId = item.id">Manage</AppButton>
                        </td>
                      </tr>
                    </tbody>
                  </AppTable>
                </div>
              </div>
            </AsyncStateGate>
          </div>
        </AppCard>
      </section>
    </div>

    <ScholarSettingsModal
      :scholar="activeScholarSettings"
      :image-url-draft="activeScholarSettings ? (imageUrlDraftByScholarId[activeScholarSettings.id] ?? '') : ''"
      :image-busy="activeScholarSettings ? isImageBusy(activeScholarSettings.id) : false"
      :image-saving="activeScholarSettings ? imageSavingScholarId === activeScholarSettings.id : false"
      :image-uploading="activeScholarSettings ? imageUploadingScholarId === activeScholarSettings.id : false"
      :saving="saving"
      @close="activeScholarSettingsId = null"
      @update:image-url-draft="v => { if (activeScholarSettings) imageUrlDraftByScholarId[activeScholarSettings.id] = v; }"
      @save-image-url="onSaveImageUrl"
      @upload-image="onUploadImage"
      @reset-image="onResetImage"
      @toggle="onToggleScholar"
      @delete="onDeleteScholar"
    />
  </AppPage>
</template>
