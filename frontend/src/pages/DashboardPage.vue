<script setup lang="ts">
import { onMounted, ref } from "vue";

import { fetchDashboardSnapshot, type DashboardSnapshot } from "@/features/dashboard";
import { triggerManualRun } from "@/features/runs";
import { ApiRequestError } from "@/lib/api/errors";
import AppPage from "@/components/layout/AppPage.vue";
import AsyncStateGate from "@/components/patterns/AsyncStateGate.vue";
import QueueHealthBadge from "@/components/patterns/QueueHealthBadge.vue";
import RequestStateAlerts from "@/components/patterns/RequestStateAlerts.vue";
import RunStatusBadge from "@/components/patterns/RunStatusBadge.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppEmptyState from "@/components/ui/AppEmptyState.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import { useAuthStore } from "@/stores/auth";

const loading = ref(true);
const pendingRun = ref(false);
const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);
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

async function onTriggerRun(): Promise<void> {
  pendingRun.value = true;
  errorMessage.value = null;
  errorRequestId.value = null;
  successMessage.value = null;

  try {
    const result = await triggerManualRun();
    successMessage.value = `Update check #${result.run_id} started successfully.`;
    await loadSnapshot();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to start an update check.";
    }
  } finally {
    pendingRun.value = false;
  }
}

onMounted(() => {
  void loadSnapshot();
});
</script>

<template>
  <AppPage
    title="Dashboard"
    subtitle="Track recent publication updates and monitor background profile checks."
    fill
  >
    <div class="flex min-h-0 flex-1 flex-col gap-4">
      <RequestStateAlerts
        :success-message="successMessage"
        :error-message="errorMessage"
        :error-request-id="errorRequestId"
        error-title="Dashboard request failed"
        @dismiss-success="successMessage = null"
      />

      <div class="min-h-0 flex-1">
        <AsyncStateGate :loading="loading" :loading-lines="6" :show-empty="false">
          <template v-if="snapshot">
            <section class="grid min-h-0 gap-4 xl:h-full xl:grid-cols-2">
              <AppCard class="flex min-h-0 flex-col gap-4 xl:h-full xl:overflow-hidden">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <div class="space-y-1">
                    <div class="flex items-center gap-1">
                      <h2 class="text-lg font-semibold text-ink-primary">Recent Publications</h2>
                      <AppHelpHint
                        text="Recent publications are paper records discovered from tracked scholar profile checks."
                      />
                    </div>
                    <p class="text-sm text-secondary">Newest papers found while checking your tracked scholar profiles.</p>
                  </div>
                  <RouterLink to="/publications" class="link-inline text-sm">Open full publications view</RouterLink>
                </div>

                <AppEmptyState
                  v-if="snapshot.recentPublications.length === 0"
                  title="No new publications"
                  body="When a completed update check discovers changes, they will appear here."
                />

                <ul v-else class="grid min-h-0 flex-1 gap-3 overflow-y-auto pr-1">
                  <li
                    v-for="item in snapshot.recentPublications.slice(0, 20)"
                    :key="item.publication_id"
                    class="grid gap-1 rounded-xl border border-stroke-default bg-surface-card-muted px-3 py-2"
                  >
                    <a
                      v-if="item.pub_url"
                      :href="item.pub_url"
                      target="_blank"
                      rel="noreferrer"
                      class="link-inline text-sm font-semibold text-ink-primary"
                    >
                      {{ item.title }}
                    </a>
                    <span v-else class="text-sm font-semibold text-ink-primary">{{ item.title }}</span>
                    <div class="flex flex-wrap items-center gap-3 text-xs text-secondary">
                      <RouterLink
                        :to="{ name: 'publications', query: { scholar: String(item.scholar_profile_id) } }"
                        class="link-inline"
                      >
                        {{ item.scholar_label }}
                      </RouterLink>
                      <span>First seen: {{ formatDate(item.first_seen_at) }}</span>
                    </div>
                  </li>
                </ul>
              </AppCard>

              <div class="grid min-h-0 gap-4 xl:h-full xl:grid-rows-[auto_minmax(0,1fr)]">
                <AppCard class="flex min-h-0 flex-col gap-4">
                  <div class="flex items-center gap-1">
                    <h2 class="text-lg font-semibold text-ink-primary">Overview</h2>
                    <AppHelpHint text="Shared summary metrics for publication coverage and processing pressure." />
                  </div>
                  <div class="grid gap-3 sm:grid-cols-2">
                    <article class="rounded-xl border border-stroke-default bg-surface-card-muted px-3 py-2">
                      <p class="text-xs uppercase tracking-wide text-ink-muted">Tracked publications</p>
                      <p class="mt-1 text-xl font-semibold text-ink-primary">{{ snapshot.totalCount }}</p>
                    </article>
                    <article class="rounded-xl border border-stroke-default bg-surface-card-muted px-3 py-2">
                      <p class="text-xs uppercase tracking-wide text-ink-muted">New from latest check</p>
                      <p class="mt-1 text-xl font-semibold text-ink-primary">{{ snapshot.newCount }}</p>
                    </article>
                    <article class="rounded-xl border border-stroke-default bg-surface-card-muted px-3 py-2">
                      <p class="text-xs uppercase tracking-wide text-ink-muted">Scholars processed</p>
                      <p class="mt-1 text-xl font-semibold text-ink-primary">{{ snapshot.latestRun?.scholar_count ?? 0 }}</p>
                    </article>
                    <article class="rounded-xl border border-stroke-default bg-surface-card-muted px-3 py-2">
                      <p class="text-xs uppercase tracking-wide text-ink-muted">Queue pressure</p>
                      <p class="mt-1 text-xl font-semibold text-ink-primary">
                        {{ snapshot.queue.queued + snapshot.queue.retrying + snapshot.queue.dropped }}
                      </p>
                    </article>
                  </div>
                  <QueueHealthBadge
                    :queued="snapshot.queue.queued"
                    :retrying="snapshot.queue.retrying"
                    :dropped="snapshot.queue.dropped"
                  />
                </AppCard>

                <AppCard class="flex min-h-0 flex-col gap-4 xl:overflow-hidden">
                  <div class="flex flex-wrap items-center justify-between gap-2">
                    <div class="flex items-center gap-1">
                      <h2 class="text-lg font-semibold text-ink-primary">Activity Monitor</h2>
                      <AppHelpHint
                        text="Combines latest profile-check details with recent check history so you can spot issues quickly."
                      />
                    </div>
                    <div class="flex items-center gap-2">
                      <AppButton
                        v-if="auth.isAdmin"
                        :disabled="pendingRun"
                        @click="onTriggerRun"
                      >
                        {{ pendingRun ? "Starting..." : "Start check" }}
                      </AppButton>
                      <RouterLink
                        v-if="auth.isAdmin"
                        to="/admin/runs"
                        class="link-inline text-sm"
                      >
                        Open check history
                      </RouterLink>
                    </div>
                  </div>

                  <div
                    v-if="snapshot.latestRun"
                    class="rounded-xl border border-stroke-default bg-surface-card-muted px-3 py-2"
                  >
                    <div class="flex flex-wrap items-center justify-between gap-2">
                      <div class="flex items-center gap-2">
                        <RunStatusBadge :status="snapshot.latestRun.status" />
                        <span class="text-sm font-semibold text-ink-primary">Latest check #{{ snapshot.latestRun.id }}</span>
                      </div>
                      <RouterLink
                        v-if="auth.isAdmin"
                        :to="`/admin/runs/${snapshot.latestRun.id}`"
                        class="link-inline text-xs"
                      >
                        View diagnostics
                      </RouterLink>
                    </div>
                    <p class="mt-2 text-sm text-secondary">
                      Started {{ formatDate(snapshot.latestRun.start_dt) }}. Processed
                      {{ snapshot.latestRun.scholar_count }} scholars and discovered
                      {{ snapshot.latestRun.new_publication_count }} new publications.
                    </p>
                  </div>
                  <AppEmptyState
                    v-else
                    title="No checks recorded"
                    body="Start an update check to begin monitoring activity."
                  />

                  <div class="grid min-h-0 flex-1 gap-2 xl:overflow-hidden">
                    <p class="text-xs font-semibold uppercase tracking-wide text-muted">Recent checks</p>
                    <AppEmptyState
                      v-if="snapshot.recentRuns.length === 0"
                      title="No checks yet"
                      body="Check history will appear here."
                    />
                    <ul v-else class="grid gap-2 overflow-y-auto pr-1">
                      <li
                        v-for="run in snapshot.recentRuns"
                        :key="run.id"
                        class="grid gap-1 rounded-xl border border-stroke-default bg-surface-card-muted px-3 py-2"
                      >
                        <div class="flex items-center justify-between gap-2">
                          <div class="flex items-center gap-2">
                            <RunStatusBadge :status="run.status" />
                            <span class="text-sm text-secondary">Check #{{ run.id }}</span>
                          </div>
                          <RouterLink v-if="auth.isAdmin" :to="`/admin/runs/${run.id}`" class="link-inline text-xs">
                            Details
                          </RouterLink>
                        </div>
                        <span class="text-xs text-secondary">
                          {{ formatDate(run.start_dt) }} • {{ run.new_publication_count }} new
                        </span>
                      </li>
                    </ul>
                  </div>
                </AppCard>
              </div>
            </section>
          </template>
        </AsyncStateGate>
      </div>
    </div>
  </AppPage>
</template>
