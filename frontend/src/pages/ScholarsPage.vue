<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import AppPage from "@/components/layout/AppPage.vue";
import AsyncStateGate from "@/components/patterns/AsyncStateGate.vue";
import RequestStateAlerts from "@/components/patterns/RequestStateAlerts.vue";
import AppAlert from "@/components/ui/AppAlert.vue";
import AppBadge from "@/components/ui/AppBadge.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppModal from "@/components/ui/AppModal.vue";
import AppSelect from "@/components/ui/AppSelect.vue";
import AppTable from "@/components/ui/AppTable.vue";
import {
  clearScholarImage,
  createScholar,
  deleteScholar,
  listScholars,
  searchScholarsByName,
  setScholarImageUrl,
  toggleScholar,
  uploadScholarImage,
  type ScholarProfile,
  type ScholarSearchCandidate,
  type ScholarSearchResult,
} from "@/features/scholars";
import ScholarAvatar from "@/features/scholars/components/ScholarAvatar.vue";
import { ApiRequestError } from "@/lib/api/errors";

const loading = ref(true);
const saving = ref(false);
const searchingByName = ref(false);
const activeScholarId = ref<number | null>(null);
const imageSavingScholarId = ref<number | null>(null);
const imageUploadingScholarId = ref<number | null>(null);
const addingCandidateScholarId = ref<string | null>(null);
const activeScholarSettingsId = ref<number | null>(null);

const scholars = ref<ScholarProfile[]>([]);
const imageUrlDraftByScholarId = ref<Record<number, string>>({});

const scholarBatchInput = ref("");
const searchQuery = ref("");
const trackedFilterQuery = ref("");
type TrackedScholarSort = "recent" | "name_asc" | "name_desc" | "enabled_first";
const trackedSort = ref<TrackedScholarSort>("recent");
const searchResult = ref<ScholarSearchResult | null>(null);
const searchErrorMessage = ref<string | null>(null);
const searchErrorRequestId = ref<string | null>(null);

const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);

const SCHOLAR_ID_PATTERN = /^[a-zA-Z0-9_-]{12}$/;
const URL_USER_PARAM_PATTERN = /(?:\?|&)user=([a-zA-Z0-9_-]{12})(?:&|#|$)/i;
const nameSearchWip = true;

const trackedScholarIds = computed(() => new Set(scholars.value.map((item) => item.scholar_id)));
const activeScholarSettings = computed(
  () => scholars.value.find((item) => item.id === activeScholarSettingsId.value) ?? null,
);
const hasTrackedScholars = computed(() => scholars.value.length > 0);
const parsedBatchCount = computed(() => parseScholarIds(scholarBatchInput.value).length);
const searchHasRun = computed(() => searchResult.value !== null);
const searchIsDegraded = computed(() => {
  if (!searchResult.value) {
    return false;
  }
  return searchResult.value.state === "blocked_or_captcha" || searchResult.value.state === "network_error";
});
const searchStateTone = computed(() => {
  const result = searchResult.value;
  if (!result) {
    return "neutral" as const;
  }
  if (result.state === "ok") {
    return "success" as const;
  }
  if (result.state === "blocked_or_captcha" || result.state === "network_error") {
    return "warning" as const;
  }
  return "neutral" as const;
});
const emptySearchCandidates = computed(() => {
  const result = searchResult.value;
  if (!result) {
    return false;
  }
  return result.candidates.length === 0;
});
const normalizedTrackedFilter = computed(() => trackedFilterQuery.value.trim().toLocaleLowerCase());
const visibleScholars = computed(() => {
  const filter = normalizedTrackedFilter.value;
  const filtered = scholars.value.filter((item) => {
    if (!filter) {
      return true;
    }
    const label = scholarLabel(item).toLocaleLowerCase();
    const scholarId = item.scholar_id.toLocaleLowerCase();
    return label.includes(filter) || scholarId.includes(filter);
  });

  const byName = (a: ScholarProfile, b: ScholarProfile) =>
    scholarLabel(a).localeCompare(scholarLabel(b), undefined, { sensitivity: "base" });

  const sorted = [...filtered];
  if (trackedSort.value === "name_asc") {
    sorted.sort(byName);
    return sorted;
  }
  if (trackedSort.value === "name_desc") {
    sorted.sort((a, b) => byName(b, a));
    return sorted;
  }
  if (trackedSort.value === "enabled_first") {
    sorted.sort((a, b) => {
      if (a.is_enabled !== b.is_enabled) {
        return a.is_enabled ? -1 : 1;
      }
      return byName(a, b);
    });
    return sorted;
  }

  sorted.sort((a, b) => b.id - a.id);
  return sorted;
});
const hasVisibleScholars = computed(() => visibleScholars.value.length > 0);
const trackedCountLabel = computed(() => {
  if (!normalizedTrackedFilter.value) {
    return `${scholars.value.length} tracked`;
  }
  return `${visibleScholars.value.length} of ${scholars.value.length}`;
});

function scholarProfileUrl(scholarId: string): string {
  return `https://scholar.google.com/citations?hl=en&user=${encodeURIComponent(scholarId)}`;
}

function scholarPublicationsRoute(profile: ScholarProfile): { name: string; query: { scholar: string } } {
  return {
    name: "publications",
    query: { scholar: String(profile.id) },
  };
}

function parseScholarIds(raw: string): string[] {
  const ordered: string[] = [];
  const seen = new Set<string>();

  const tokens = raw
    .split(/[\s,;]+/)
    .map((value) => value.trim())
    .filter((value) => value.length > 0);

  for (const token of tokens) {
    let candidate: string | null = null;

    if (SCHOLAR_ID_PATTERN.test(token)) {
      candidate = token;
    }

    if (!candidate) {
      const directParamMatch = token.match(URL_USER_PARAM_PATTERN);
      if (directParamMatch) {
        candidate = directParamMatch[1];
      }
    }

    if (!candidate && token.includes("scholar.google")) {
      try {
        const parsed = new URL(token);
        const userParam = parsed.searchParams.get("user");
        if (userParam && SCHOLAR_ID_PATTERN.test(userParam)) {
          candidate = userParam;
        }
      } catch (_error) {
        // Ignore non-URL tokens.
      }
    }

    if (!candidate || seen.has(candidate)) {
      continue;
    }

    seen.add(candidate);
    ordered.push(candidate);
  }

  return ordered;
}

function scholarLabel(profile: ScholarProfile): string {
  return profile.display_name || profile.scholar_id;
}

function isImageBusy(scholarProfileId: number): boolean {
  return (
    imageSavingScholarId.value === scholarProfileId ||
    imageUploadingScholarId.value === scholarProfileId ||
    activeScholarId.value === scholarProfileId
  );
}

function openScholarSettings(profile: ScholarProfile): void {
  activeScholarSettingsId.value = profile.id;
}

function closeScholarSettings(): void {
  activeScholarSettingsId.value = null;
}

function syncImageDrafts(): void {
  const next: Record<number, string> = {};
  for (const item of scholars.value) {
    const existing = imageUrlDraftByScholarId.value[item.id];
    if (typeof existing === "string" && existing.length > 0) {
      next[item.id] = existing;
      continue;
    }

    next[item.id] = item.profile_image_source === "override" ? (item.profile_image_url ?? "") : "";
  }
  imageUrlDraftByScholarId.value = next;
}

async function loadScholars(): Promise<void> {
  loading.value = true;

  try {
    scholars.value = await listScholars();
    syncImageDrafts();
  } catch (error) {
    scholars.value = [];
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

async function onAddScholars(): Promise<void> {
  saving.value = true;
  errorMessage.value = null;
  errorRequestId.value = null;
  successMessage.value = null;

  try {
    const scholarIds = parseScholarIds(scholarBatchInput.value);
    if (scholarIds.length === 0) {
      throw new Error("Provide at least one valid Scholar ID or profile URL.");
    }

    const settled = await Promise.allSettled(
      scholarIds.map((scholarId) => createScholar({ scholar_id: scholarId })),
    );

    const failures: string[] = [];
    let requestIdFromFailures: string | null = null;
    let createdCount = 0;

    settled.forEach((result, index) => {
      if (result.status === "fulfilled") {
        createdCount += 1;
        return;
      }

      const scholarId = scholarIds[index];
      if (result.reason instanceof ApiRequestError) {
        failures.push(`${scholarId}: ${result.reason.message}`);
        if (!requestIdFromFailures && result.reason.requestId) {
          requestIdFromFailures = result.reason.requestId;
        }
      } else if (result.reason instanceof Error) {
        failures.push(`${scholarId}: ${result.reason.message}`);
      } else {
        failures.push(`${scholarId}: Unable to create scholar.`);
      }
    });

    if (createdCount > 0) {
      const total = scholarIds.length;
      successMessage.value = `Added ${createdCount} of ${total} scholar${total === 1 ? "" : "s"}.`;
      scholarBatchInput.value = "";
    }

    if (failures.length > 0) {
      const preview = failures.slice(0, 3).join(" | ");
      const remainder = failures.length > 3 ? ` (+${failures.length - 3} more)` : "";
      errorMessage.value = `Failed to add ${failures.length} scholar${failures.length === 1 ? "" : "s"}: ${preview}${remainder}`;
      errorRequestId.value = requestIdFromFailures;
    }

    await loadScholars();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else if (error instanceof Error) {
      errorMessage.value = error.message;
    } else {
      errorMessage.value = "Unable to create scholar records.";
    }
  } finally {
    saving.value = false;
  }
}

async function onSearchByName(): Promise<void> {
  if (nameSearchWip) {
    searchErrorMessage.value = "Search by name is temporarily disabled while reliability hardening is in progress.";
    searchErrorRequestId.value = null;
    return;
  }
  searchingByName.value = true;
  searchErrorMessage.value = null;
  searchErrorRequestId.value = null;

  try {
    const normalized = searchQuery.value.trim();
    if (normalized.length < 2) {
      throw new Error("Enter at least 2 characters to search.");
    }

    searchResult.value = await searchScholarsByName(normalized, 12);
  } catch (error) {
    searchResult.value = null;
    if (error instanceof ApiRequestError) {
      searchErrorMessage.value = error.message;
      searchErrorRequestId.value = error.requestId;
    } else if (error instanceof Error) {
      searchErrorMessage.value = error.message;
    } else {
      searchErrorMessage.value = "Unable to search scholars by name.";
    }
  } finally {
    searchingByName.value = false;
  }
}

async function onAddCandidate(candidate: ScholarSearchCandidate): Promise<void> {
  addingCandidateScholarId.value = candidate.scholar_id;
  errorMessage.value = null;
  errorRequestId.value = null;
  successMessage.value = null;

  try {
    await createScholar({
      scholar_id: candidate.scholar_id,
      profile_image_url: candidate.profile_image_url ?? undefined,
    });
    successMessage.value = `${candidate.display_name} added.`;
    await loadScholars();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to add scholar from search result.";
    }
  } finally {
    addingCandidateScholarId.value = null;
  }
}

async function onToggleScholar(profile: ScholarProfile): Promise<void> {
  activeScholarId.value = profile.id;
  errorMessage.value = null;
  errorRequestId.value = null;
  successMessage.value = null;

  try {
    await toggleScholar(profile.id);
    successMessage.value = `${scholarLabel(profile)} ${profile.is_enabled ? "disabled" : "enabled"}.`;
    await loadScholars();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to update scholar status.";
    }
  } finally {
    activeScholarId.value = null;
  }
}

async function onDeleteScholar(profile: ScholarProfile): Promise<void> {
  const label = scholarLabel(profile);
  const shouldDelete = window.confirm(`Delete scholar ${label}? This removes all linked publications and queue data.`);
  if (!shouldDelete) {
    return;
  }

  activeScholarId.value = profile.id;
  errorMessage.value = null;
  errorRequestId.value = null;
  successMessage.value = null;

  try {
    await deleteScholar(profile.id);
    successMessage.value = `${label} deleted.`;
    if (activeScholarSettingsId.value === profile.id) {
      closeScholarSettings();
    }
    await loadScholars();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to delete scholar.";
    }
  } finally {
    activeScholarId.value = null;
  }
}

async function onSaveImageUrl(profile: ScholarProfile): Promise<void> {
  const candidate = (imageUrlDraftByScholarId.value[profile.id] || "").trim();
  if (!candidate) {
    errorMessage.value = "Enter an image URL before saving, or use Reset image.";
    return;
  }

  imageSavingScholarId.value = profile.id;
  errorMessage.value = null;
  errorRequestId.value = null;
  successMessage.value = null;

  try {
    await setScholarImageUrl(profile.id, candidate);
    successMessage.value = `Image URL updated for ${scholarLabel(profile)}.`;
    await loadScholars();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to update scholar image URL.";
    }
  } finally {
    imageSavingScholarId.value = null;
  }
}

async function onUploadImage(profile: ScholarProfile, event: Event): Promise<void> {
  const input = event.target as HTMLInputElement | null;
  const file = input?.files?.[0] ?? null;
  if (!file) {
    return;
  }

  imageUploadingScholarId.value = profile.id;
  errorMessage.value = null;
  errorRequestId.value = null;
  successMessage.value = null;

  try {
    await uploadScholarImage(profile.id, file);
    successMessage.value = `Uploaded image for ${scholarLabel(profile)}.`;
    await loadScholars();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to upload scholar image.";
    }
  } finally {
    imageUploadingScholarId.value = null;
    if (input) {
      input.value = "";
    }
  }
}

async function onResetImage(profile: ScholarProfile): Promise<void> {
  imageSavingScholarId.value = profile.id;
  errorMessage.value = null;
  errorRequestId.value = null;
  successMessage.value = null;

  try {
    await clearScholarImage(profile.id);
    successMessage.value = `Image reset for ${scholarLabel(profile)}.`;
    await loadScholars();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to reset scholar image.";
    }
  } finally {
    imageSavingScholarId.value = null;
  }
}

onMounted(() => {
  void loadScholars();
});
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
          <AppCard class="space-y-4 xl:flex xl:min-h-0 xl:flex-col">
            <div class="space-y-1">
              <div class="flex items-center gap-1">
                <h2 class="text-lg font-semibold text-ink-primary">Add Scholar Profiles</h2>
                <AppHelpHint
                  text="A scholar profile is a Google Scholar author page that Scholarr will monitor for publication changes."
                />
              </div>
              <p class="text-sm text-secondary">Paste one or more Scholar IDs or profile URLs and add them in one action.</p>
            </div>

            <form class="grid gap-3" @submit.prevent="onAddScholars">
              <label class="grid gap-2 text-sm font-medium text-ink-secondary" for="scholar-batch-input">
                <span>Scholar IDs or profile URLs</span>
                <textarea
                  id="scholar-batch-input"
                  v-model="scholarBatchInput"
                  rows="5"
                  placeholder="A-UbBTPM15wL\nhttps://scholar.google.com/citations?hl=en&user=A-UbBTPM15wL"
                  class="w-full rounded-lg border border-stroke-interactive bg-surface-input px-3 py-2 text-sm text-ink-primary outline-none ring-focus-ring transition placeholder:text-ink-muted focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset disabled:cursor-not-allowed disabled:opacity-60"
                />
              </label>

              <div class="flex flex-wrap items-center justify-between gap-2">
                <p class="text-xs text-secondary">
                  Parsed IDs: <strong class="text-ink-primary">{{ parsedBatchCount }}</strong>
                </p>
                <AppButton type="submit" :disabled="saving || loading">
                  {{ saving ? "Adding..." : "Add scholars" }}
                </AppButton>
              </div>
            </form>
          </AppCard>

          <AppCard class="relative space-y-4 select-none xl:flex xl:min-h-0 xl:flex-col xl:overflow-hidden">
            <div class="flex flex-wrap items-start justify-between gap-2">
              <div class="space-y-1">
                <div class="flex items-center gap-1">
                  <h2 class="text-lg font-semibold text-ink-primary">Search by Name</h2>
                  <AppHelpHint text="Google Scholar now challenges this endpoint with account login and anti-bot checks, so this workflow stays disabled." />
                </div>
                <p class="text-sm text-secondary">
                  This helper remains paused because Google Scholar currently requires account login for reliable name search access.
                </p>
              </div>
              <AppHelpHint text="Name search is kept as WIP. Use direct Scholar ID or profile URL adds for production tracking.">
                <template #trigger>
                  <AppBadge tone="warning">WIP</AppBadge>
                </template>
              </AppHelpHint>
            </div>

            <form class="pointer-events-none flex flex-wrap items-center gap-2 opacity-60">
              <div class="min-w-0 flex-1">
                <AppInput
                  id="scholar-search-name"
                  v-model="searchQuery"
                  placeholder="e.g. Geoffrey Hinton"
                  :disabled="nameSearchWip"
                />
              </div>
              <AppButton type="button" :disabled="nameSearchWip">
                Search
              </AppButton>
            </form>
            <p class="text-xs text-secondary">
              Direct Scholar ID/URL adds above are the supported path until name search can run without login challenges.
            </p>

            <div class="min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-1">
              <RequestStateAlerts
                :error-message="searchErrorMessage"
                :error-request-id="searchErrorRequestId"
                error-title="Search request failed"
              />

              <AsyncStateGate :loading="searchingByName" :loading-lines="4" :show-empty="false">
                <template v-if="searchResult">
                  <div class="flex flex-wrap items-center justify-between gap-2">
                    <p class="text-sm text-secondary">
                      {{ searchResult.candidates.length }} candidate{{ searchResult.candidates.length === 1 ? "" : "s" }}
                      for <strong class="text-ink-primary">{{ searchResult.query }}</strong>
                    </p>
                    <AppBadge :tone="searchStateTone">{{ searchResult.state }}</AppBadge>
                  </div>

                  <p v-if="searchResult.state !== 'ok' || searchResult.warnings.length > 0" class="text-xs text-secondary">
                    <span>State reason: <code>{{ searchResult.state_reason }}</code></span>
                    <span v-if="searchResult.action_hint">. {{ searchResult.action_hint }}</span>
                    <span v-if="searchResult.warnings.length > 0">. Warnings: {{ searchResult.warnings.join(", ") }}</span>
                  </p>

                  <AppAlert v-if="searchIsDegraded" tone="warning">
                    <template #title>Name search is degraded</template>
                    <p>
                      This endpoint throttles aggressively to avoid blocks. Use Scholar URL/ID adds for dependable tracking.
                    </p>
                  </AppAlert>

                  <AsyncStateGate
                    :loading="false"
                    :show-empty="true"
                    :empty="emptySearchCandidates"
                    empty-title="No scholar matches returned"
                    empty-body="Try another query later or add directly by Scholar URL/ID."
                  >
                    <ul class="grid gap-3">
                      <li
                        v-for="candidate in searchResult.candidates"
                        :key="candidate.scholar_id"
                        class="rounded-xl border border-stroke-default bg-surface-card-muted/70 p-3"
                      >
                        <div class="flex items-start gap-3">
                          <ScholarAvatar
                            size="sm"
                            :label="candidate.display_name"
                            :scholar-id="candidate.scholar_id"
                            :image-url="candidate.profile_image_url"
                          />

                          <div class="min-w-0 flex-1 space-y-1">
                            <div class="flex flex-wrap items-center gap-2">
                              <strong class="text-sm text-ink-primary">{{ candidate.display_name }}</strong>
                              <code class="text-xs text-secondary">{{ candidate.scholar_id }}</code>
                              <AppBadge v-if="trackedScholarIds.has(candidate.scholar_id)" tone="success">Tracked</AppBadge>
                            </div>

                            <p class="truncate text-xs text-secondary">{{ candidate.affiliation || "No affiliation provided" }}</p>

                            <div class="flex flex-wrap items-center gap-2 text-xs text-secondary">
                              <span v-if="candidate.email_domain">Email: {{ candidate.email_domain }}</span>
                              <span v-if="candidate.cited_by_count !== null">Cited by: {{ candidate.cited_by_count }}</span>
                            </div>
                          </div>

                          <div class="grid shrink-0 gap-2">
                            <AppButton
                              :disabled="trackedScholarIds.has(candidate.scholar_id) || addingCandidateScholarId === candidate.scholar_id"
                              @click="onAddCandidate(candidate)"
                            >
                              {{ addingCandidateScholarId === candidate.scholar_id ? "Adding..." : "Add" }}
                            </AppButton>
                            <a :href="candidate.profile_url" target="_blank" rel="noreferrer" class="link-inline text-xs text-center">
                              Open profile
                            </a>
                          </div>
                        </div>
                      </li>
                    </ul>
                  </AsyncStateGate>
                </template>
                <p v-else-if="!searchErrorMessage && !searchHasRun" class="text-sm text-secondary">
                  Name search remains disabled while login-gated responses are unresolved.
                </p>
              </AsyncStateGate>
            </div>
          </AppCard>
        </div>

        <AppCard class="flex min-h-0 flex-col gap-4 xl:order-1 xl:h-full xl:overflow-hidden">
          <div class="space-y-3">
            <div class="space-y-1">
              <div class="flex items-center gap-1">
                <h2 class="text-lg font-semibold text-ink-primary">Tracked Scholars</h2>
                <AppHelpHint
                  text="Tracked scholars are active profile sources. Open Manage to control status, image overrides, and removal."
                />
              </div>
              <p class="text-sm text-secondary">Review tracked profiles, filter quickly, and open per-scholar settings when needed.</p>
            </div>
            <div class="grid gap-3 rounded-xl border border-stroke-default bg-surface-card-muted/70 px-3 py-2">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <p class="text-xs font-medium uppercase tracking-wide text-secondary">Tracking status</p>
                <div class="flex flex-wrap items-center gap-2">
                  <span
                    class="inline-flex min-h-10 items-center rounded-lg border border-state-info-border bg-state-info-bg px-3 text-sm font-semibold text-state-info-text"
                  >
                    {{ trackedCountLabel }}
                  </span>
                  <AppButton variant="secondary" :disabled="loading || saving" @click="loadScholars">
                    {{ loading ? "Refreshing..." : "Refresh" }}
                  </AppButton>
                </div>
              </div>

              <div class="grid gap-2 sm:grid-cols-[minmax(0,1fr)_12rem]">
                <label class="grid gap-1 text-xs font-medium uppercase tracking-wide text-secondary" for="tracked-scholar-filter">
                  <span>Filter tracked scholars</span>
                  <AppInput
                    id="tracked-scholar-filter"
                    v-model="trackedFilterQuery"
                    placeholder="Filter by name or scholar ID"
                  />
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
            <AsyncStateGate
              :loading="loading"
              :loading-lines="6"
              :empty="!hasTrackedScholars"
              :show-empty="!errorMessage"
              empty-title="No scholars tracked"
              empty-body="Add a Scholar ID or URL to start ingestion tracking."
            >
              <AppEmptyState
                v-if="!hasVisibleScholars"
                title="No scholars match this filter"
                body="Clear or adjust the filter to see tracked scholars."
              />

              <div v-else class="space-y-3 xl:flex xl:h-full xl:min-h-0 xl:flex-col xl:space-y-0">
                <ul class="grid gap-3 lg:hidden">
                  <li
                    v-for="item in visibleScholars"
                    :key="item.id"
                    class="rounded-xl border border-stroke-default bg-surface-card-muted/70 p-3"
                  >
                    <div class="flex items-start gap-3">
                      <ScholarAvatar :label="item.display_name" :scholar-id="item.scholar_id" :image-url="item.profile_image_url" />

                      <div class="min-w-0 flex-1 space-y-1">
                        <p class="truncate text-sm font-semibold text-ink-primary">{{ scholarLabel(item) }}</p>
                        <div class="flex flex-wrap items-center gap-3">
                          <RouterLink :to="scholarPublicationsRoute(item)" class="link-inline text-xs">
                            Publications
                          </RouterLink>
                          <a :href="scholarProfileUrl(item.scholar_id)" target="_blank" rel="noreferrer" class="link-inline text-xs">
                            Open profile
                          </a>
                        </div>
                      </div>

                      <AppButton variant="secondary" :disabled="saving" @click="openScholarSettings(item)">Manage</AppButton>
                    </div>
                  </li>
                </ul>

                <div class="hidden min-h-0 flex-1 lg:block">
                  <AppTable class="max-h-full overflow-y-auto" label="Tracked scholars table">
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
                                <RouterLink :to="scholarPublicationsRoute(item)" class="link-inline text-xs">
                                  Publications
                                </RouterLink>
                                <a :href="scholarProfileUrl(item.scholar_id)" target="_blank" rel="noreferrer" class="link-inline text-xs">
                                  Open profile
                                </a>
                              </div>
                            </div>
                          </div>
                        </td>
                        <td>
                          <AppButton variant="secondary" :disabled="saving" @click="openScholarSettings(item)">Manage</AppButton>
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

    <AppModal :open="activeScholarSettings !== null" title="Scholar settings" @close="closeScholarSettings">
      <div v-if="activeScholarSettings" class="grid gap-4">
        <div class="flex items-start gap-3">
          <ScholarAvatar
            :label="activeScholarSettings.display_name"
            :scholar-id="activeScholarSettings.scholar_id"
            :image-url="activeScholarSettings.profile_image_url"
          />

          <div class="min-w-0 space-y-1">
            <p class="truncate text-sm font-semibold text-ink-primary">
              {{ scholarLabel(activeScholarSettings) }}
            </p>
            <p class="text-xs text-secondary">
              ID: <code>{{ activeScholarSettings.scholar_id }}</code>
            </p>
            <div class="flex flex-wrap items-center gap-3">
              <RouterLink :to="scholarPublicationsRoute(activeScholarSettings)" class="link-inline text-xs">
                View publications
              </RouterLink>
              <a
                :href="scholarProfileUrl(activeScholarSettings.scholar_id)"
                target="_blank"
                rel="noreferrer"
                class="link-inline text-xs"
              >
                Open Google Scholar profile
              </a>
            </div>
          </div>
        </div>

        <div class="grid gap-2">
          <label class="text-sm font-medium text-ink-secondary" :for="`scholar-image-url-${activeScholarSettings.id}`">
            Profile image URL override
          </label>
          <div class="flex flex-wrap items-center gap-2">
            <div class="min-w-0 flex-1">
              <AppInput
                :id="`scholar-image-url-${activeScholarSettings.id}`"
                v-model="imageUrlDraftByScholarId[activeScholarSettings.id]"
                placeholder="https://example.com/avatar.jpg"
                :disabled="isImageBusy(activeScholarSettings.id)"
              />
            </div>
            <AppButton
              variant="secondary"
              :disabled="isImageBusy(activeScholarSettings.id)"
              @click="onSaveImageUrl(activeScholarSettings)"
            >
              {{ imageSavingScholarId === activeScholarSettings.id ? "Saving..." : "Save URL" }}
            </AppButton>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <label
              :for="`scholar-image-upload-${activeScholarSettings.id}`"
              class="inline-flex min-h-10 cursor-pointer items-center justify-center rounded-lg border border-stroke-strong bg-action-secondary-bg px-3 py-2 text-sm font-semibold text-action-secondary-text transition hover:bg-action-secondary-hover-bg focus-within:outline-none focus-within:ring-2 focus-within:ring-focus-ring focus-within:ring-offset-2 focus-within:ring-offset-focus-offset"
              :class="{ 'pointer-events-none opacity-60': isImageBusy(activeScholarSettings.id) }"
            >
              {{ imageUploadingScholarId === activeScholarSettings.id ? "Uploading..." : "Upload image" }}
            </label>
            <input
              :id="`scholar-image-upload-${activeScholarSettings.id}`"
              type="file"
              class="sr-only"
              accept="image/jpeg,image/png,image/webp,image/gif"
              :disabled="isImageBusy(activeScholarSettings.id)"
              @change="onUploadImage(activeScholarSettings, $event)"
            />
            <AppButton variant="ghost" :disabled="isImageBusy(activeScholarSettings.id)" @click="onResetImage(activeScholarSettings)">
              Reset image
            </AppButton>
          </div>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-2 border-t border-stroke-default pt-3">
          <AppButton
            variant="secondary"
            :disabled="isImageBusy(activeScholarSettings.id) || saving"
            @click="onToggleScholar(activeScholarSettings)"
          >
            {{ activeScholarSettings.is_enabled ? "Disable scholar" : "Enable scholar" }}
          </AppButton>
          <AppButton
            variant="danger"
            :disabled="isImageBusy(activeScholarSettings.id) || saving"
            @click="onDeleteScholar(activeScholarSettings)"
          >
            Delete scholar
          </AppButton>
        </div>
      </div>
    </AppModal>
  </AppPage>
</template>
