<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import AppPage from "@/components/layout/AppPage.vue";
import RunStatusBadge from "@/components/patterns/RunStatusBadge.vue";
import AppAlert from "@/components/ui/AppAlert.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppEmptyState from "@/components/ui/AppEmptyState.vue";
import AppSkeleton from "@/components/ui/AppSkeleton.vue";
import AppTable from "@/components/ui/AppTable.vue";
import { getRunDetail, type RunDetail } from "@/features/runs";
import { ApiRequestError } from "@/lib/api/errors";

const route = useRoute();

const loading = ref(true);
const detail = ref<RunDetail | null>(null);
const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);

const runId = computed(() => Number(route.params.id));

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
    <div class="flex justify-end">
      <AppButton variant="secondary" @click="loadDetail" :disabled="loading">
        {{ loading ? "Refreshing..." : "Refresh" }}
      </AppButton>
    </div>

    <AppAlert v-if="errorMessage" tone="danger">
      <template #title>Run detail request failed</template>
      <p>{{ errorMessage }}</p>
      <p class="text-secondary">Request ID: {{ errorRequestId || "n/a" }}</p>
    </AppAlert>

    <AppSkeleton v-if="loading" :lines="8" />

    <template v-else-if="detail">
      <AppCard class="space-y-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="space-y-1">
            <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Run #{{ detail.run.id }}</h2>
            <p class="text-sm text-secondary">Started: {{ formatDate(detail.run.start_dt) }}</p>
            <p class="text-sm text-secondary">Ended: {{ formatDate(detail.run.end_dt) }}</p>
          </div>
          <RunStatusBadge :status="detail.run.status" />
        </div>

        <p class="text-sm text-zinc-700 dark:text-zinc-300">
          Outcome summary: {{ detail.summary.succeeded_count }} succeeded, {{ detail.summary.partial_count }} partial,
          {{ detail.summary.failed_count }} failed.
        </p>
      </AppCard>

      <AppCard class="space-y-4">
        <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Scholar Results</h2>
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
  </AppPage>
</template>
