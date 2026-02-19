<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import AppPage from "@/components/layout/AppPage.vue";
import AsyncStateGate from "@/components/patterns/AsyncStateGate.vue";
import RequestStateAlerts from "@/components/patterns/RequestStateAlerts.vue";
import RunStatusBadge from "@/components/patterns/RunStatusBadge.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppEmptyState from "@/components/ui/AppEmptyState.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppTable from "@/components/ui/AppTable.vue";
import { getRunDetail, type RunDetail } from "@/features/runs";
import { ApiRequestError } from "@/lib/api/errors";

const route = useRoute();

const loading = ref(true);
const detail = ref<RunDetail | null>(null);
const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);

const runId = computed(() => Number(route.params.id));
const defaultRetryCounts = {
  retries_scheduled_count: 0,
  scholars_with_retries_count: 0,
  retry_exhausted_count: 0,
};

function sortedCountEntries(record: Record<string, number> | null | undefined): Array<[string, number]> {
  if (!record) {
    return [];
  }
  return Object.entries(record)
    .filter(([, value]) => Number.isFinite(value) && value > 0)
    .sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0]));
}

const failureBucketEntries = computed(() =>
  detail.value ? sortedCountEntries(detail.value.summary.scrape_failure_counts) : [],
);

const alertFlagEntries = computed(() => {
  if (!detail.value) {
    return [];
  }
  return Object.entries(detail.value.summary.alert_flags ?? {})
    .filter(([, enabled]) => Boolean(enabled))
    .sort((a, b) => a[0].localeCompare(b[0]));
});

const retryCounts = computed(() => detail.value?.summary.retry_counts ?? defaultRetryCounts);

function formatDate(value: string | null): string {
  if (!value) {
    return "n/a";
  }
  const asDate = new Date(value);
  if (Number.isNaN(asDate.getTime())) {
    return value;
  }
  return asDate.toLocaleString();
}

async function loadDetail(): Promise<void> {
  loading.value = true;
  errorMessage.value = null;
  errorRequestId.value = null;

  if (!Number.isFinite(runId.value) || runId.value <= 0) {
    detail.value = null;
    errorMessage.value = "Invalid run id.";
    loading.value = false;
    return;
  }

  try {
    detail.value = await getRunDetail(runId.value);
  } catch (error) {
    detail.value = null;
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to load run details.";
    }
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void loadDetail();
});
</script>

<template>
  <AppPage title="Run Detail" subtitle="Per-scholar diagnostics for the selected run.">
    <AppCard class="space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="space-y-1">
          <div class="flex items-center gap-1">
            <h2 class="text-lg font-semibold text-ink-primary">Diagnostics controls</h2>
            <AppHelpHint
              text="Run diagnostics explain per-scholar outcomes, retry behavior, and scrape failure classifications."
            />
          </div>
          <p class="text-sm text-secondary">Refresh this run detail view after queue/run updates.</p>
        </div>
        <AppButton variant="secondary" @click="loadDetail" :disabled="loading">
          {{ loading ? "Refreshing..." : "Refresh" }}
        </AppButton>
      </div>
    </AppCard>

    <RequestStateAlerts
      :error-message="errorMessage"
      :error-request-id="errorRequestId"
      error-title="Run detail request failed"
    />

    <AsyncStateGate :loading="loading" :loading-lines="8" :show-empty="false">
      <template v-if="detail">
      <AppCard class="space-y-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="space-y-1">
            <div class="flex items-center gap-1">
              <h2 class="text-lg font-semibold text-ink-primary">Run #{{ detail.run.id }}</h2>
              <AppHelpHint text="This panel summarizes one full checking cycle and its completion status." />
            </div>
            <p class="text-sm text-secondary">Started: {{ formatDate(detail.run.start_dt) }}</p>
            <p class="text-sm text-secondary">Ended: {{ formatDate(detail.run.end_dt) }}</p>
          </div>
          <RunStatusBadge :status="detail.run.status" />
        </div>

        <p class="text-sm text-ink-secondary">
          Outcome summary: {{ detail.summary.succeeded_count }} succeeded, {{ detail.summary.partial_count }} partial,
          {{ detail.summary.failed_count }} failed.
        </p>
        <div class="grid gap-3 md:grid-cols-3">
          <div class="rounded-xl border border-stroke-default bg-surface-card-muted px-3 py-2 text-sm">
            <p class="font-medium text-ink-primary">Retries scheduled</p>
            <p>{{ retryCounts.retries_scheduled_count }}</p>
          </div>
          <div class="rounded-xl border border-stroke-default bg-surface-card-muted px-3 py-2 text-sm">
            <p class="font-medium text-ink-primary">Scholars with retries</p>
            <p>{{ retryCounts.scholars_with_retries_count }}</p>
          </div>
          <div class="rounded-xl border border-stroke-default bg-surface-card-muted px-3 py-2 text-sm">
            <p class="font-medium text-ink-primary">Retry exhausted</p>
            <p>{{ retryCounts.retry_exhausted_count }}</p>
          </div>
        </div>
        <div class="grid gap-3 md:grid-cols-2">
          <div class="rounded-xl border border-stroke-default bg-surface-card-muted px-3 py-2 text-sm">
            <p class="font-medium text-ink-primary">Scrape failure buckets</p>
            <p v-if="failureBucketEntries.length === 0" class="text-secondary">n/a</p>
            <ul v-else class="space-y-1">
              <li v-for="[name, count] in failureBucketEntries" :key="name">
                <code>{{ name }}</code>: {{ count }}
              </li>
            </ul>
          </div>
          <div class="rounded-xl border border-stroke-default bg-surface-card-muted px-3 py-2 text-sm">
            <p class="font-medium text-ink-primary">Active alerts</p>
            <p v-if="alertFlagEntries.length === 0" class="text-secondary">none</p>
            <ul v-else class="space-y-1">
              <li v-for="[name] in alertFlagEntries" :key="name">
                <code>{{ name }}</code>
              </li>
            </ul>
          </div>
        </div>
      </AppCard>

      <AppCard class="space-y-4">
        <div class="flex items-center gap-1">
          <h2 class="text-lg font-semibold text-ink-primary">Scholar Results</h2>
          <AppHelpHint text="One row per scholar profile processed in this run, including final state and warnings." />
        </div>
        <AppEmptyState
          v-if="detail.scholar_results.length === 0"
          title="No scholar diagnostics"
          body="This run did not include per-scholar diagnostics payloads."
        />

        <AppTable v-else label="Run detail scholar diagnostics table">
          <thead>
            <tr>
              <th scope="col">Scholar ID</th>
              <th scope="col">Outcome</th>
              <th scope="col">State</th>
              <th scope="col">Publications</th>
              <th scope="col">Attempts</th>
              <th scope="col">Warnings</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="result in detail.scholar_results" :key="`${result.scholar_profile_id}-${result.scholar_id}`">
              <td><code>{{ result.scholar_id }}</code></td>
              <td>{{ result.outcome }}</td>
              <td>{{ result.state }}<span v-if="result.state_reason"> ({{ result.state_reason }})</span></td>
              <td>{{ result.publication_count }}</td>
              <td>{{ result.attempt_count }}</td>
              <td>{{ result.warnings.length ? result.warnings.join(", ") : "n/a" }}</td>
            </tr>
          </tbody>
        </AppTable>
      </AppCard>
      </template>
    </AsyncStateGate>
  </AppPage>
</template>
