<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import AppPage from "@/components/layout/AppPage.vue";
import QueueHealthBadge from "@/components/patterns/QueueHealthBadge.vue";
import RunStatusBadge from "@/components/patterns/RunStatusBadge.vue";
import AppAlert from "@/components/ui/AppAlert.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppEmptyState from "@/components/ui/AppEmptyState.vue";
import AppSkeleton from "@/components/ui/AppSkeleton.vue";
import AppTable from "@/components/ui/AppTable.vue";
import {
  clearQueueItem,
  dropQueueItem,
  listQueueItems,
  listRuns,
  retryQueueItem,
  triggerManualRun,
  type QueueItem,
  type RunListItem,
} from "@/features/runs";
import { ApiRequestError } from "@/lib/api/errors";

const loading = ref(true);
const pendingRun = ref(false);
const runs = ref<RunListItem[]>([]);
const queueItems = ref<QueueItem[]>([]);
const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);
const activeQueueItemId = ref<number | null>(null);

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

async function loadData(): Promise<void> {
  loading.value = true;
  errorMessage.value = null;
  errorRequestId.value = null;

  try {
    const [loadedRuns, loadedQueue] = await Promise.all([listRuns({ limit: 100 }), listQueueItems(200)]);
    runs.value = loadedRuns;
    queueItems.value = loadedQueue;
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
  pendingRun.value = true;
  successMessage.value = null;

  try {
    const result = await triggerManualRun();
    successMessage.value = `Manual run queued as #${result.run_id} (${result.status}).`;
    await loadData();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to trigger manual run.";
    }
  } finally {
    pendingRun.value = false;
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
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex flex-wrap items-center gap-2">
        <AppButton :disabled="pendingRun" @click="onTriggerManualRun">
          {{ pendingRun ? "Triggering..." : "Run now" }}
        </AppButton>
        <AppButton variant="secondary" :disabled="loading" @click="loadData">
          {{ loading ? "Refreshing..." : "Refresh" }}
        </AppButton>
      </div>

      <QueueHealthBadge
        :queued="queueCounts.queued"
        :retrying="queueCounts.retrying"
        :dropped="queueCounts.dropped"
      />
    </div>

    <AppAlert v-if="successMessage" tone="success" dismissible @dismiss="successMessage = null">
      <template #title>Operation complete</template>
      <p>{{ successMessage }}</p>
    </AppAlert>

    <AppAlert v-if="errorMessage" tone="danger">
      <template #title>Run diagnostics request failed</template>
      <p>{{ errorMessage }}</p>
      <p class="text-secondary">Request ID: {{ errorRequestId || "n/a" }}</p>
    </AppAlert>

    <AppSkeleton v-if="loading" :lines="8" />

    <template v-else>
      <AppCard class="space-y-4">
        <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Recent Runs</h2>
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
        <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Continuation Queue</h2>
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
    </template>
  </AppPage>
</template>
