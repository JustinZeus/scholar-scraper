<script setup lang="ts">
import { computed, ref } from "vue";
import AsyncStateGate from "@/components/patterns/AsyncStateGate.vue";
import RequestStateAlerts from "@/components/patterns/RequestStateAlerts.vue";
import AppAlert from "@/components/ui/AppAlert.vue";
import AppBadge from "@/components/ui/AppBadge.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppInput from "@/components/ui/AppInput.vue";
import ScholarAvatar from "@/features/scholars/components/ScholarAvatar.vue";
import type { ScholarSearchCandidate, ScholarSearchResult } from "@/features/scholars";

defineProps<{
  trackedScholarIds: Set<string>;
  addingCandidateScholarId: string | null;
}>();

const emit = defineEmits<{
  (e: "add-candidate", candidate: ScholarSearchCandidate): void;
}>();

const nameSearchWip = true;
const searchingByName = ref(false);
const searchQuery = ref("");
const searchResult = ref<ScholarSearchResult | null>(null);
const searchErrorMessage = ref<string | null>(null);
const searchErrorRequestId = ref<string | null>(null);

const searchHasRun = computed(() => searchResult.value !== null);
const searchIsDegraded = computed(() => {
  if (!searchResult.value) return false;
  return searchResult.value.state === "blocked_or_captcha" || searchResult.value.state === "network_error";
});
const searchStateTone = computed(() => {
  const result = searchResult.value;
  if (!result) return "neutral" as const;
  if (result.state === "ok") return "success" as const;
  if (result.state === "blocked_or_captcha" || result.state === "network_error") return "warning" as const;
  return "neutral" as const;
});
const emptySearchCandidates = computed(() => {
  const result = searchResult.value;
  if (!result) return false;
  return result.candidates.length === 0;
});
</script>

<template>
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
            <p>This endpoint throttles aggressively to avoid blocks. Use Scholar URL/ID adds for dependable tracking.</p>
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
                      @click="emit('add-candidate', candidate)"
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
</template>
