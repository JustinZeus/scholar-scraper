<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import AppPage from "@/components/layout/AppPage.vue";
import AsyncStateGate from "@/components/patterns/AsyncStateGate.vue";
import QueueHealthBadge from "@/components/patterns/QueueHealthBadge.vue";
import RequestStateAlerts from "@/components/patterns/RequestStateAlerts.vue";
import RunStatusBadge from "@/components/patterns/RunStatusBadge.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppEmptyState from "@/components/ui/AppEmptyState.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppTable from "@/components/ui/AppTable.vue";
import {
  clearQueueItem,
  dropQueueItem,
  listQueueItems,
  listRuns,
  retryQueueItem,
  type QueueItem,
  type RunListItem,
} from "@/features/runs";
import { ApiRequestError } from "@/lib/api/errors";
import { useRunStatusStore } from "@/stores/run_status";

const loading = ref(true);
const runs = ref<RunListItem[]>([]);
const queueItems = ref<QueueItem[]>([]);
const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);
const activeQueueItemId = ref<number | null>(null);
const runStatus = useRunStatusStore();

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

function queueHealth() {
  const counts = { queued: 0, retrying: 0, dropped: 0 };
  for (const item of queueItems.value) {
    if (item.status === "queued") {
      counts.queued += 1;
    } else if (item.status === "retrying") {
      counts.retrying += 1;
    } else if (item.status === "dropped") {
      counts.dropped += 1;
    }
  }
  return counts;
}

const queueCounts = computed(() => queueHealth());
const activeRunId = computed(() => runStatus.latestRun?.status === "running" ? runStatus.latestRun.id : null);
const runButtonLabel = computed(() => {
  if (runStatus.isLikelyRunning) {
    return "Check in progress";
  }
  if (runStatus.isSubmitting) {
    return "Starting...";
  }
  return "Run now";
});

async function loadData(): Promise<void> {
  loading.value = true;
  errorMessage.value = null;
  errorRequestId.value = null;

  try {
    const [loadedRuns, loadedQueue] = await Promise.all([listRuns({ limit: 100 }), listQueueItems(200)]);
    runs.value = loadedRuns;
    queueItems.value = loadedQueue;
    runStatus.setLatestRun(loadedRuns[0] ?? null);
  } catch (error) {
    runs.value = [];
    queueItems.value = [];
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to load runs and queue diagnostics.";
    }
  } finally {
    loading.value = false;
  }
}

async function onTriggerManualRun(): Promise<void> {
  successMessage.value = null;
  errorMessage.value = null;
  errorRequestId.value = null;

  try {
    const result = await runStatus.startManualCheck();
    if (result.kind === "started") {
      successMessage.value = `Update check #${result.runId} started successfully.`;
      await loadData();
      return;
    }

    if (result.kind === "already_running") {
      successMessage.value = result.runId
        ? `Update check #${result.runId} is already in progress.`
        : "An update check is already in progress.";
      await loadData();
      return;
    }

    errorMessage.value = result.message;
    errorRequestId.value = result.requestId;
  } catch {
    errorMessage.value = "Unable to start an update check.";
    errorRequestId.value = null;
  }
}

async function runQueueAction(itemId: number, action: "retry" | "drop" | "clear"): Promise<void> {
  activeQueueItemId.value = itemId;
  successMessage.value = null;

  try {
    if (action === "retry") {
      await retryQueueItem(itemId);
      successMessage.value = `Queue item #${itemId} moved to retry.`;
    } else if (action === "drop") {
      await dropQueueItem(itemId);
      successMessage.value = `Queue item #${itemId} dropped.`;
    } else {
      await clearQueueItem(itemId);
      successMessage.value = `Queue item #${itemId} cleared.`;
    }
    await loadData();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to update queue item.";
    }
  } finally {
    activeQueueItemId.value = null;
  }
}

onMounted(() => {
  void loadData();
});
</script>

<template>
  <AppPage title="Runs" subtitle="Manual run controls and continuation queue diagnostics.">
    <AppCard class="space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="space-y-1">
          <div class="flex items-center gap-1">
            <h2 class="text-lg font-semibold text-ink-primary">Run controls</h2>
            <AppHelpHint
              text="A run is one full publication-check cycle across eligible tracked scholar profiles."
            />
          </div>
          <p class="text-sm text-secondary">Trigger runs and monitor continuation-queue pressure.</p>
        </div>
        <QueueHealthBadge
          :queued="queueCounts.queued"
          :retrying="queueCounts.retrying"
          :dropped="queueCounts.dropped"
        />
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <AppButton :disabled="runStatus.isRunActive" @click="onTriggerManualRun">
          {{ runButtonLabel }}
        </AppButton>
        <AppButton variant="secondary" :disabled="loading" @click="loadData">
          {{ loading ? "Refreshing..." : "Refresh" }}
        </AppButton>
      </div>
      <div
        v-if="runStatus.isLikelyRunning"
        class="flex flex-wrap items-center gap-2 rounded-xl border border-state-info-border bg-state-info-bg px-3 py-2 text-sm text-state-info-text"
      >
        <RunStatusBadge status="running" />
        <span class="font-medium">A publication check is currently running.</span>
        <RouterLink v-if="activeRunId" :to="`/admin/runs/${activeRunId}`" class="link-inline text-xs">
          View live check details
        </RouterLink>
      </div>
    </AppCard>

    <RequestStateAlerts
      :success-message="successMessage"
      :error-message="errorMessage"
      :error-request-id="errorRequestId"
      error-title="Run diagnostics request failed"
      @dismiss-success="successMessage = null"
    />

    <AsyncStateGate :loading="loading" :loading-lines="8" :show-empty="false">
      <AppCard class="space-y-4">
        <div class="flex items-center gap-1">
          <h2 class="text-lg font-semibold text-ink-primary">Recent Runs</h2>
          <AppHelpHint text="Recent run history with volume and failure indicators per cycle." />
        </div>
        <AppEmptyState
          v-if="runs.length === 0"
          title="No runs found"
          body="Manual or scheduled ingestion runs will appear here."
        />

        <AppTable v-else label="Recent runs table">
          <thead>
            <tr>
              <th scope="col">Run</th>
              <th scope="col">Status</th>
              <th scope="col">Started</th>
              <th scope="col">Scholars</th>
              <th scope="col">New pubs</th>
              <th scope="col">Failures</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="run in runs" :key="run.id">
              <td>
                <RouterLink
                  :to="`/admin/runs/${run.id}`"
                  class="link-inline"
                >
                  Run #{{ run.id }}
                </RouterLink>
              </td>
              <td><RunStatusBadge :status="run.status" /></td>
              <td>{{ formatDate(run.start_dt) }}</td>
              <td>{{ run.scholar_count }}</td>
              <td>{{ run.new_publication_count }}</td>
              <td>{{ run.failed_count + run.partial_count }}</td>
            </tr>
          </tbody>
        </AppTable>
      </AppCard>

      <AppCard class="space-y-4">
        <div class="flex items-center gap-1">
          <h2 class="text-lg font-semibold text-ink-primary">Continuation Queue</h2>
          <AppHelpHint
            text="Retry queue for interrupted profile checks. Use actions to retry, drop, or clear items."
          />
        </div>
        <AppEmptyState
          v-if="queueItems.length === 0"
          title="Queue is empty"
          body="Retrying and dropped continuation items appear here for admin action."
        />

        <AppTable v-else label="Continuation queue table">
          <thead>
            <tr>
              <th scope="col">ID</th>
              <th scope="col">Scholar</th>
              <th scope="col">Status</th>
              <th scope="col">Attempts</th>
              <th scope="col">Next attempt</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in queueItems" :key="item.id">
              <td>{{ item.id }}</td>
              <td>{{ item.scholar_label }}</td>
              <td>{{ item.status }}</td>
              <td>{{ item.attempt_count }}</td>
              <td>{{ formatDate(item.next_attempt_dt) }}</td>
              <td>
                <div class="flex flex-wrap items-center gap-2">
                  <AppButton
                    variant="ghost"
                    :disabled="activeQueueItemId === item.id"
                    @click="runQueueAction(item.id, 'retry')"
                  >
                    Retry
                  </AppButton>
                  <AppButton
                    variant="danger"
                    :disabled="activeQueueItemId === item.id"
                    @click="runQueueAction(item.id, 'drop')"
                  >
                    Drop
                  </AppButton>
                  <AppButton
                    variant="secondary"
                    :disabled="activeQueueItemId === item.id"
                    @click="runQueueAction(item.id, 'clear')"
                  >
                    Clear
                  </AppButton>
                </div>
              </td>
            </tr>
          </tbody>
        </AppTable>
      </AppCard>
    </AsyncStateGate>
  </AppPage>
</template>
