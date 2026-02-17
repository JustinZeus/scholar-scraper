<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import AppPage from "@/components/layout/AppPage.vue";
import RunStatusBadge from "@/components/patterns/RunStatusBadge.vue";
import AppAlert from "@/components/ui/AppAlert.vue";
import AppBadge from "@/components/ui/AppBadge.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppEmptyState from "@/components/ui/AppEmptyState.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppModal from "@/components/ui/AppModal.vue";
import AppSkeleton from "@/components/ui/AppSkeleton.vue";
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
const failedImageByKey = ref<Record<string, boolean>>({});

const scholarBatchInput = ref("");
const searchQuery = ref("");
const searchResult = ref<ScholarSearchResult | null>(null);
const searchErrorMessage = ref<string | null>(null);
const searchErrorRequestId = ref<string | null>(null);

const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);

const SCHOLAR_ID_PATTERN = /^[a-zA-Z0-9_-]{12}$/;
const URL_USER_PARAM_PATTERN = /(?:\?|&)user=([a-zA-Z0-9_-]{12})(?:&|#|$)/i;

const trackedScholarIds = computed(() => new Set(scholars.value.map((item) => item.scholar_id)));
const activeScholarSettings = computed(
  () => scholars.value.find((item) => item.id === activeScholarSettingsId.value) ?? null,
);
const searchIsDegraded = computed(() => {
  if (!searchResult.value) {
    return false;
  }
  return searchResult.value.state === "blocked_or_captcha" || searchResult.value.state === "network_error";
});

function formatDate(value: string | null, compact = false): string {
  if (!value) {
    return "n/a";
  }
  const asDate = new Date(value);
  if (Number.isNaN(asDate.getTime())) {
    return value;
  }
  if (compact) {
    return asDate.toLocaleString(undefined, {
      dateStyle: "short",
      timeStyle: "short",
    });
  }
  return asDate.toLocaleString();
}

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

function formatImageSource(value: ScholarProfile["profile_image_source"]): string {
  if (value === "upload") {
    return "Uploaded";
  }
  if (value === "override") {
    return "Custom URL";
  }
  if (value === "scraped") {
    return "Scraped";
  }
  return "Fallback";
}

function sourceTone(value: ScholarProfile["profile_image_source"]): "neutral" | "info" | "success" {
  if (value === "upload") {
    return "success";
  }
  if (value === "override" || value === "scraped") {
    return "info";
  }
  return "neutral";
}

function makeInitials(label: string | null | undefined, scholarId: string): string {
  const source = (label || "").trim();
  if (source.length === 0) {
    return scholarId.slice(0, 2).toUpperCase();
  }

  const tokens = source.split(/\s+/).filter(Boolean);
  if (tokens.length === 1) {
    return tokens[0].slice(0, 2).toUpperCase();
  }

  return `${tokens[0].charAt(0)}${tokens[1].charAt(0)}`.toUpperCase();
}

function imageKey(prefix: string, id: string | number, imageUrl: string | null): string {
  return `${prefix}:${String(id)}:${imageUrl || "none"}`;
}

function canRenderImage(prefix: string, id: string | number, imageUrl: string | null): boolean {
  if (!imageUrl) {
    return false;
  }
  return !failedImageByKey.value[imageKey(prefix, id, imageUrl)];
}

function markImageFailed(prefix: string, id: string | number, imageUrl: string | null): void {
  failedImageByKey.value[imageKey(prefix, id, imageUrl)] = true;
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
  <AppPage title="Scholars" subtitle="Track scholars and manage profile behavior with less noise.">
    <div class="flex justify-end">
      <AppButton variant="secondary" @click="loadScholars" :disabled="loading || saving || searchingByName">
        {{ loading ? "Refreshing..." : "Refresh" }}
      </AppButton>
    </div>

    <AppAlert v-if="successMessage" tone="success" dismissible @dismiss="successMessage = null">
      <template #title>Scholar update complete</template>
      <p>{{ successMessage }}</p>
    </AppAlert>

    <AppAlert v-if="errorMessage" tone="danger">
      <template #title>Scholar request failed</template>
      <p>{{ errorMessage }}</p>
      <p class="text-secondary">Request ID: {{ errorRequestId || "n/a" }}</p>
    </AppAlert>

    <section class="grid gap-4 xl:grid-cols-[minmax(0,34rem)_minmax(0,1fr)]">
      <div class="grid content-start gap-4">
        <AppCard class="space-y-4">
          <div class="space-y-1">
            <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Add Scholars</h2>
            <p class="text-sm text-secondary">
              Paste one or many Scholar IDs or profile URLs. Duplicate and already-tracked IDs are ignored per response.
            </p>
          </div>

          <form class="grid gap-3" @submit.prevent="onAddScholars">
            <label class="grid gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
              <span>Scholar IDs or profile URLs</span>
              <textarea
                id="scholar-batch-input"
                v-model="scholarBatchInput"
                rows="5"
                placeholder="A-UbBTPM15wL\nhttps://scholar.google.com/citations?hl=en&user=A-UbBTPM15wL"
                class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none ring-brand-300 transition placeholder:text-zinc-400 focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:ring-brand-400 dark:focus-visible:ring-offset-zinc-950 dark:placeholder:text-zinc-500"
              />
            </label>

            <div class="flex flex-wrap items-center justify-between gap-2">
              <AppButton type="submit" :disabled="saving || loading">
                {{ saving ? "Adding..." : "Add scholars" }}
              </AppButton>
              <span class="text-xs text-secondary">Accepted pattern: <code>[a-zA-Z0-9_-]{12}</code></span>
            </div>
          </form>
        </AppCard>

        <AppCard class="space-y-4">
          <div class="space-y-1">
            <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Search by Name</h2>
            <p class="text-sm text-secondary">
              Best-effort helper. For reliable adds, use Scholar URL/ID above.
            </p>
          </div>

          <form class="flex flex-wrap items-center gap-2" @submit.prevent="onSearchByName">
            <div class="min-w-0 flex-1">
              <AppInput
                id="scholar-search-name"
                v-model="searchQuery"
                placeholder="e.g. Geoffrey Hinton"
                :disabled="searchingByName"
              />
            </div>
            <AppButton type="submit" :disabled="searchingByName || searchQuery.trim().length < 2">
              {{ searchingByName ? "Searching..." : "Search" }}
            </AppButton>
          </form>

          <AppAlert v-if="searchErrorMessage" tone="danger">
            <template #title>Search failed</template>
            <p>{{ searchErrorMessage }}</p>
            <p class="text-secondary">Request ID: {{ searchErrorRequestId || "n/a" }}</p>
          </AppAlert>

          <AppSkeleton v-else-if="searchingByName" :lines="4" />

          <template v-else-if="searchResult">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <p class="text-sm text-secondary">
                {{ searchResult.candidates.length }} candidate{{ searchResult.candidates.length === 1 ? "" : "s" }} for
                <strong class="text-zinc-900 dark:text-zinc-100">{{ searchResult.query }}</strong>
              </p>
              <AppBadge
                :tone="
                  searchResult.state === 'ok'
                    ? 'success'
                    : searchResult.state === 'blocked_or_captcha' || searchResult.state === 'network_error'
                      ? 'warning'
                      : 'neutral'
                "
              >
                {{ searchResult.state }}
              </AppBadge>
            </div>
            <p
              v-if="searchResult.state !== 'ok' || searchResult.warnings.length > 0"
              class="text-xs text-secondary"
            >
              <span>State reason: <code>{{ searchResult.state_reason }}</code></span>
              <span v-if="searchResult.action_hint">. {{ searchResult.action_hint }}</span>
              <span v-if="searchResult.warnings.length > 0">
                . Warnings: {{ searchResult.warnings.join(", ") }}
              </span>
            </p>

            <AppAlert v-if="searchIsDegraded" tone="warning">
              <template #title>Name search is degraded</template>
              <p>
                To avoid blocks, this feature is throttled and may temporarily pause itself. Use Scholar URL/ID adds
                for dependable tracking.
              </p>
            </AppAlert>

            <AppEmptyState
              v-if="searchResult.candidates.length === 0"
              title="No scholar matches returned"
              body="Try again later or paste Scholar profile URLs/IDs to continue safely."
            />

            <ul v-else class="grid gap-3">
              <li
                v-for="candidate in searchResult.candidates"
                :key="candidate.scholar_id"
                class="rounded-xl border border-zinc-200 bg-zinc-50/70 p-3 dark:border-zinc-800 dark:bg-zinc-900/50"
              >
                <div class="flex items-start gap-3">
                  <div
                    class="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border border-zinc-200 bg-zinc-100 text-xs font-semibold text-zinc-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200"
                  >
                    <img
                      v-if="canRenderImage('candidate', candidate.scholar_id, candidate.profile_image_url)"
                      :src="candidate.profile_image_url || ''"
                      :alt="`${candidate.display_name} profile image`"
                      class="h-full w-full object-cover"
                      loading="lazy"
                      referrerpolicy="no-referrer"
                      @error="markImageFailed('candidate', candidate.scholar_id, candidate.profile_image_url)"
                    />
                    <span v-else>{{ makeInitials(candidate.display_name, candidate.scholar_id) }}</span>
                  </div>

                  <div class="min-w-0 flex-1 space-y-1">
                    <div class="flex flex-wrap items-center gap-2">
                      <strong class="text-sm text-zinc-900 dark:text-zinc-100">{{ candidate.display_name }}</strong>
                      <code class="text-xs text-secondary">{{ candidate.scholar_id }}</code>
                      <AppBadge v-if="trackedScholarIds.has(candidate.scholar_id)" tone="success">Tracked</AppBadge>
                    </div>

                    <p class="truncate text-xs text-secondary">
                      {{ candidate.affiliation || "No affiliation provided" }}
                    </p>

                    <div class="flex flex-wrap items-center gap-2 text-xs text-secondary">
                      <span v-if="candidate.email_domain">Email: {{ candidate.email_domain }}</span>
                      <span v-if="candidate.cited_by_count !== null">Cited by: {{ candidate.cited_by_count }}</span>
                    </div>

                    <div class="flex flex-wrap items-center gap-1">
                      <AppBadge v-for="interest in candidate.interests.slice(0, 3)" :key="interest" tone="neutral">
                        {{ interest }}
                      </AppBadge>
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
          </template>

          <p v-else class="text-sm text-secondary">Run a name search to see matching scholar candidates.</p>
        </AppCard>
      </div>

      <AppCard class="space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Tracked Scholars</h2>
          <span class="text-sm text-secondary">{{ scholars.length }} total</span>
        </div>

        <AppSkeleton v-if="loading" :lines="6" />

        <AppEmptyState
          v-else-if="scholars.length === 0"
          title="No scholars tracked"
          body="Add a Scholar ID directly or search by name to start ingestion tracking."
        />

        <div v-else class="space-y-3">
          <ul class="grid gap-3 lg:hidden">
            <li
              v-for="item in scholars"
              :key="item.id"
              class="rounded-xl border border-zinc-200 bg-zinc-50/70 p-3 dark:border-zinc-800 dark:bg-zinc-900/50"
            >
              <div class="flex items-start gap-3">
                <div
                  class="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border border-zinc-200 bg-zinc-100 text-xs font-semibold text-zinc-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200"
                >
                  <img
                    v-if="canRenderImage('scholar', item.id, item.profile_image_url)"
                    :src="item.profile_image_url || ''"
                    :alt="`${scholarLabel(item)} profile image`"
                    class="h-full w-full object-cover"
                    loading="lazy"
                    referrerpolicy="no-referrer"
                    @error="markImageFailed('scholar', item.id, item.profile_image_url)"
                  />
                  <span v-else>{{ makeInitials(item.display_name, item.scholar_id) }}</span>
                </div>

                <div class="min-w-0 flex-1 space-y-1">
                  <p class="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">{{ scholarLabel(item) }}</p>
                  <p class="text-xs text-secondary"><code>{{ item.scholar_id }}</code></p>
                  <div class="flex flex-wrap items-center gap-2">
                    <AppBadge :tone="item.is_enabled ? 'success' : 'warning'">
                      {{ item.is_enabled ? "Enabled" : "Disabled" }}
                    </AppBadge>
                    <RunStatusBadge :status="item.last_run_status || 'unknown'" />
                    <span class="text-xs text-secondary">{{ formatDate(item.last_run_dt, true) }}</span>
                  </div>
                  <RouterLink :to="scholarPublicationsRoute(item)" class="link-inline text-xs">
                    View publications
                  </RouterLink>
                </div>

                <AppButton variant="secondary" :disabled="saving" @click="openScholarSettings(item)">Manage</AppButton>
              </div>
            </li>
          </ul>

          <AppTable class="hidden lg:block" label="Scholars table">
            <thead>
              <tr>
                <th scope="col">Scholar</th>
                <th scope="col">Scholar ID</th>
                <th scope="col">Enabled</th>
                <th scope="col" class="w-[15rem]">Last run</th>
                <th scope="col">Manage</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in scholars" :key="item.id">
                <td>
                  <div class="flex items-start gap-3">
                    <div
                      class="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border border-zinc-200 bg-zinc-100 text-xs font-semibold text-zinc-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200"
                    >
                      <img
                        v-if="canRenderImage('scholar', item.id, item.profile_image_url)"
                        :src="item.profile_image_url || ''"
                        :alt="`${scholarLabel(item)} profile image`"
                        class="h-full w-full object-cover"
                        loading="lazy"
                        referrerpolicy="no-referrer"
                        @error="markImageFailed('scholar', item.id, item.profile_image_url)"
                      />
                      <span v-else>{{ makeInitials(item.display_name, item.scholar_id) }}</span>
                    </div>

                    <div class="grid min-w-0 gap-1">
                      <strong class="truncate text-zinc-900 dark:text-zinc-100">{{ scholarLabel(item) }}</strong>
                      <div class="flex flex-wrap items-center gap-2">
                        <RouterLink :to="scholarPublicationsRoute(item)" class="link-inline text-xs">
                          Publications
                        </RouterLink>
                        <a :href="scholarProfileUrl(item.scholar_id)" target="_blank" rel="noreferrer" class="link-inline text-xs">
                          Open profile
                        </a>
                        <AppBadge :tone="sourceTone(item.profile_image_source)">
                          {{ formatImageSource(item.profile_image_source) }}
                        </AppBadge>
                      </div>
                    </div>
                  </div>
                </td>
                <td><code class="text-xs">{{ item.scholar_id }}</code></td>
                <td>
                  <AppBadge :tone="item.is_enabled ? 'success' : 'warning'">
                    {{ item.is_enabled ? "Enabled" : "Disabled" }}
                  </AppBadge>
                </td>
                <td>
                  <div class="grid gap-1 text-xs">
                    <RunStatusBadge :status="item.last_run_status || 'unknown'" />
                    <span class="whitespace-nowrap text-secondary">{{ formatDate(item.last_run_dt, true) }}</span>
                  </div>
                </td>
                <td>
                  <AppButton variant="secondary" :disabled="saving" @click="openScholarSettings(item)">
                    Manage
                  </AppButton>
                </td>
              </tr>
            </tbody>
          </AppTable>
        </div>
      </AppCard>
    </section>

    <AppModal :open="activeScholarSettings !== null" title="Scholar settings" @close="closeScholarSettings">
      <div v-if="activeScholarSettings" class="grid gap-4">
        <div class="flex items-start gap-3">
          <div
            class="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-full border border-zinc-200 bg-zinc-100 text-xs font-semibold text-zinc-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200"
          >
            <img
              v-if="canRenderImage('scholar', activeScholarSettings.id, activeScholarSettings.profile_image_url)"
              :src="activeScholarSettings.profile_image_url || ''"
              :alt="`${scholarLabel(activeScholarSettings)} profile image`"
              class="h-full w-full object-cover"
              loading="lazy"
              referrerpolicy="no-referrer"
              @error="markImageFailed('scholar', activeScholarSettings.id, activeScholarSettings.profile_image_url)"
            />
            <span v-else>{{ makeInitials(activeScholarSettings.display_name, activeScholarSettings.scholar_id) }}</span>
          </div>

          <div class="min-w-0 space-y-1">
            <p class="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">
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
          <label class="text-sm font-medium text-zinc-700 dark:text-zinc-300" :for="`scholar-image-url-${activeScholarSettings.id}`">
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
              class="inline-flex min-h-10 cursor-pointer items-center justify-center rounded-lg border border-zinc-300 bg-zinc-100 px-3 py-2 text-sm font-semibold text-zinc-900 transition hover:bg-zinc-200 focus-within:outline-none focus-within:ring-2 focus-within:ring-brand-500 focus-within:ring-offset-2 focus-within:ring-offset-zinc-100 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-zinc-700 dark:focus-within:ring-brand-400 dark:focus-within:ring-offset-zinc-950"
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

        <div class="flex flex-wrap items-center justify-between gap-2 border-t border-zinc-200 pt-3 dark:border-zinc-800">
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
