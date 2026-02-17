<script setup lang="ts">
import { onMounted, ref } from "vue";

import { fetchDashboardSnapshot, type DashboardSnapshot } from "@/features/dashboard";
import { ApiRequestError } from "@/lib/api/errors";
import AppPage from "@/components/layout/AppPage.vue";
import QueueHealthBadge from "@/components/patterns/QueueHealthBadge.vue";
import RunStatusBadge from "@/components/patterns/RunStatusBadge.vue";
import AppAlert from "@/components/ui/AppAlert.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppEmptyState from "@/components/ui/AppEmptyState.vue";
import AppSkeleton from "@/components/ui/AppSkeleton.vue";
import { useAuthStore } from "@/stores/auth";

const loading = ref(true);
const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const snapshot = ref<DashboardSnapshot | null>(null);
const auth = useAuthStore();

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

async function loadSnapshot(): Promise<void> {
  loading.value = true;
  errorMessage.value = null;
  errorRequestId.value = null;

  try {
    snapshot.value = await fetchDashboardSnapshot();
  } catch (error) {
    snapshot.value = null;
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to load dashboard data.";
    }
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void loadSnapshot();
});
</script>

<template>
  <AppPage title="Dashboard" subtitle="What changed since the latest run.">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <AppButton variant="secondary" @click="loadSnapshot" :disabled="loading">
        {{ loading ? "Refreshing..." : "Refresh" }}
      </AppButton>
      <QueueHealthBadge
        v-if="snapshot"
        :queued="snapshot.queue.queued"
        :retrying="snapshot.queue.retrying"
        :dropped="snapshot.queue.dropped"
      />
    </div>

    <AppAlert v-if="errorMessage" tone="danger">
      <template #title>Dashboard request failed</template>
      <p>{{ errorMessage }}</p>
      <p class="text-secondary">Request ID: {{ errorRequestId || "n/a" }}</p>
    </AppAlert>

    <AppSkeleton v-if="loading" :lines="6" />

    <template v-else-if="snapshot">
      <section class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <AppCard class="space-y-4">
          <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Snapshot Summary</h2>
          <p class="text-sm text-secondary">Latest view mode: {{ snapshot.mode }}</p>
          <ul class="grid gap-2 text-sm text-zinc-700 dark:text-zinc-300">
            <li class="rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900/60">
              Latest run introduced
              <span class="font-semibold text-zinc-900 dark:text-zinc-100">{{ snapshot.newCount }}</span>
              publications.
            </li>
            <li class="rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900/60">
              Total tracked publications:
              <span class="font-semibold text-zinc-900 dark:text-zinc-100">{{ snapshot.totalCount }}</span>
            </li>
          </ul>
        </AppCard>

        <AppCard class="space-y-4">
          <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Latest Run</h2>
          <div v-if="snapshot.latestRun" class="space-y-2 text-sm">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <RunStatusBadge :status="snapshot.latestRun.status" />
              <RouterLink
                v-if="auth.isAdmin"
                :to="`/admin/runs/${snapshot.latestRun.id}`"
                class="link-inline"
              >
                Run #{{ snapshot.latestRun.id }}
              </RouterLink>
              <span v-else class="text-secondary">Run #{{ snapshot.latestRun.id }}</span>
            </div>
            <p class="text-secondary">Started: {{ formatDate(snapshot.latestRun.start_dt) }}</p>
            <p class="text-muted">
              {{ snapshot.latestRun.scholar_count }} scholars, {{ snapshot.latestRun.new_publication_count }} new
              publications
            </p>
          </div>
          <AppEmptyState
            v-else
            title="No runs recorded"
            body="Trigger a manual run from the Runs screen to begin tracking."
          />
        </AppCard>
      </section>

      <section class="grid gap-4 xl:grid-cols-2">
        <AppCard class="space-y-4">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Recent Publications</h2>
            <RouterLink
              to="/publications"
              class="link-inline text-sm"
            >
              Open publications
            </RouterLink>
          </div>
          <AppEmptyState
            v-if="snapshot.recentPublications.length === 0"
            title="No new publications"
            body="When a completed run discovers updates, they will appear here."
          />
          <ul v-else class="grid gap-3">
            <li
              v-for="item in snapshot.recentPublications.slice(0, 6)"
              :key="item.publication_id"
              class="grid gap-1 rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900/60"
            >
              <strong class="text-zinc-900 dark:text-zinc-100">{{ item.title }}</strong>
              <span class="text-secondary">{{ item.scholar_label }}</span>
            </li>
          </ul>
        </AppCard>

        <AppCard class="space-y-4">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Recent Runs</h2>
            <RouterLink
              v-if="auth.isAdmin"
              to="/admin/runs"
              class="link-inline text-sm"
            >
              Open runs
            </RouterLink>
          </div>
          <AppEmptyState
            v-if="snapshot.recentRuns.length === 0"
            title="No runs yet"
            body="Trigger a manual run from the Runs screen to begin tracking."
          />
          <ul v-else class="grid gap-3">
            <li
              v-for="run in snapshot.recentRuns"
              :key="run.id"
              class="grid gap-1 rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900/60"
            >
              <div class="flex items-center gap-2">
                <RunStatusBadge :status="run.status" />
                <span class="text-secondary">Run #{{ run.id }}</span>
              </div>
              <span class="text-secondary">{{ formatDate(run.start_dt) }}</span>
            </li>
          </ul>
        </AppCard>
      </section>
    </template>
  </AppPage>
</template>
