<script setup lang="ts">
import { computed, ref } from "vue";
import { useAuthStore } from "@/stores/auth";
import AppBadge from "@/components/ui/AppBadge.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppRefreshButton from "@/components/ui/AppRefreshButton.vue";
import AppSelect from "@/components/ui/AppSelect.vue";
import AppTable from "@/components/ui/AppTable.vue";
import RequestStateAlerts from "@/components/patterns/RequestStateAlerts.vue";
import {
  listAdminPdfQueue,
  requeueAdminPdfLookup,
  requeueAllAdminPdfLookups,
  type AdminPdfQueueItem,
} from "@/features/admin_dbops";
import { useRequestState } from "@/composables/useRequestState";

const { errorMessage, errorRequestId, successMessage, clearAlerts, assignError, setSuccess } = useRequestState();
const auth = useAuthStore();

const refreshingPdfQueue = ref(false);
const requeueingPublicationId = ref<number | null>(null);
const requeueingAllPdfs = ref(false);
const pdfQueueItems = ref<AdminPdfQueueItem[]>([]);
const pdfQueueStatusFilter = ref("");
const pdfQueuePage = ref(1);
const pdfQueuePageSize = ref("50");
const pdfQueueTotalCount = ref(0);
const pdfQueueHasNext = ref(false);
const pdfQueueHasPrev = ref(false);

const pdfQueuePageSizeValue = computed(() => {
  const parsed = Number(pdfQueuePageSize.value);
  if (!Number.isFinite(parsed)) return 50;
  return Math.max(1, Math.min(500, Math.trunc(parsed)));
});
const pdfQueueTotalPages = computed(() =>
  Math.max(1, Math.ceil(pdfQueueTotalCount.value / Math.max(pdfQueuePageSizeValue.value, 1))),
);
const pdfQueueSummary = computed(() =>
  `${pdfQueueTotalCount.value} item${pdfQueueTotalCount.value === 1 ? "" : "s"} total`,
);

function statusTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "ok" || status === "completed" || status === "resolved") return "success";
  if (status === "warning" || status === "running" || status === "queued") return "warning";
  if (status === "failed") return "danger";
  return "info";
}

function formatTimestamp(value: string | null): string {
  if (!value) return "n/a";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function canRequeuePdf(item: AdminPdfQueueItem): boolean {
  return item.status !== "queued" && item.status !== "running";
}

async function refreshPdfQueue(): Promise<void> {
  refreshingPdfQueue.value = true;
  try {
    const status = pdfQueueStatusFilter.value.trim() || null;
    const page = await listAdminPdfQueue(pdfQueuePage.value, pdfQueuePageSizeValue.value, status);
    pdfQueueItems.value = page.items;
    pdfQueueTotalCount.value = page.total_count;
    pdfQueueHasNext.value = page.has_next;
    pdfQueueHasPrev.value = page.has_prev;
    pdfQueuePage.value = page.page;
    pdfQueuePageSize.value = String(page.page_size);
  } finally {
    refreshingPdfQueue.value = false;
  }
}

async function onPdfQueueFilterChanged(): Promise<void> {
  pdfQueuePage.value = 1;
  await refreshPdfQueue();
}

async function onPdfQueuePageSizeChanged(): Promise<void> {
  pdfQueuePage.value = 1;
  await refreshPdfQueue();
}

async function onPdfQueuePrevPage(): Promise<void> {
  if (!pdfQueueHasPrev.value || pdfQueuePage.value <= 1) return;
  pdfQueuePage.value = Math.max(pdfQueuePage.value - 1, 1);
  await refreshPdfQueue();
}

async function onPdfQueueNextPage(): Promise<void> {
  if (!pdfQueueHasNext.value) return;
  pdfQueuePage.value += 1;
  await refreshPdfQueue();
}

async function onRequeuePdf(item: AdminPdfQueueItem): Promise<void> {
  requeueingPublicationId.value = item.publication_id;
  clearAlerts();
  try {
    const result = await requeueAdminPdfLookup(item.publication_id);
    setSuccess(result.message);
    await refreshPdfQueue();
  } catch (error) {
    assignError(error, "Unable to requeue PDF lookup.");
  } finally {
    requeueingPublicationId.value = null;
  }
}

async function onRequeueAllPdfs(): Promise<void> {
  requeueingAllPdfs.value = true;
  clearAlerts();
  try {
    const result = await requeueAllAdminPdfLookups(5000);
    setSuccess(result.message);
    await refreshPdfQueue();
  } catch (error) {
    assignError(error, "Unable to queue missing PDF lookups.");
  } finally {
    requeueingAllPdfs.value = false;
  }
}

async function load(): Promise<void> {
  await refreshPdfQueue();
}

defineExpose({ load });
</script>

<template>
  <section class="grid gap-4">
    <RequestStateAlerts
      :success-message="successMessage"
      :error-message="errorMessage"
      :error-request-id="errorRequestId"
      success-title="PDF queue operation complete"
      error-title="PDF queue operation failed"
      @dismiss-success="successMessage = null"
    />

    <AppCard class="space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-1">
        <h2 class="text-lg font-semibold text-ink-primary">PDF Gathering Queue</h2>
        <AppHelpHint text="Live queue and outcome history for PDF acquisition across all publications." />
      </div>
      <div class="flex items-center gap-2">
        <AppSelect v-model="pdfQueueStatusFilter" class="min-w-[12rem] !py-1.5 !text-sm" @change="onPdfQueueFilterChanged">
          <option value="">All statuses</option>
          <option value="untracked">untracked</option>
          <option value="queued">queued</option>
          <option value="running">running</option>
          <option value="failed">failed</option>
          <option value="resolved">resolved</option>
        </AppSelect>
        <AppSelect v-model="pdfQueuePageSize" class="min-w-[10rem] !py-1.5 !text-sm" @change="onPdfQueuePageSizeChanged">
          <option value="25">25 / page</option>
          <option value="50">50 / page</option>
          <option value="100">100 / page</option>
        </AppSelect>
        <AppButton v-if="auth.isAdmin" variant="secondary" class="!min-h-8 whitespace-nowrap !px-2.5 !py-1 !text-xs" :disabled="requeueingAllPdfs" title="Queue all missing PDFs" @click="onRequeueAllPdfs">
          {{ requeueingAllPdfs ? "Queueing..." : "Queue all" }}
        </AppButton>
        <AppRefreshButton variant="secondary" size="sm" :loading="refreshingPdfQueue" title="Refresh PDF queue" loading-title="Refreshing PDF queue" @click="refreshPdfQueue" />
      </div>
    </div>

    <AppTable label="PDF queue table">
      <thead>
        <tr>
          <th scope="col">Publication</th><th scope="col">Status</th><th scope="col">Attempts</th>
          <th scope="col">Failure reason</th><th scope="col">Source</th><th scope="col">Requested by</th>
          <th scope="col">Queued</th><th scope="col">Last attempt</th><th scope="col">Resolved</th><th scope="col">Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in pdfQueueItems" :key="item.publication_id">
          <td>
            <div class="grid gap-1">
              <span class="font-medium text-ink-primary">{{ item.title }}</span>
              <a v-if="item.display_identifier?.url" :href="item.display_identifier.url" target="_blank" rel="noreferrer" class="link-inline text-xs">{{ item.display_identifier.label }}</a>
            </div>
          </td>
          <td><AppBadge :tone="statusTone(item.status)">{{ item.status }}</AppBadge></td>
          <td>{{ item.attempt_count }}</td>
          <td>{{ item.last_failure_reason || "n/a" }}</td>
          <td>{{ item.last_source || "n/a" }}</td>
          <td>{{ item.requested_by_email || "n/a" }}</td>
          <td>{{ formatTimestamp(item.queued_at) }}</td>
          <td>{{ formatTimestamp(item.last_attempt_at) }}</td>
          <td>{{ formatTimestamp(item.resolved_at) }}</td>
          <td>
            <AppButton v-if="auth.isAdmin" variant="ghost" :disabled="requeueingPublicationId === item.publication_id || !canRequeuePdf(item)" @click="onRequeuePdf(item)">
              {{ requeueingPublicationId === item.publication_id ? "Requeueing..." : "Requeue" }}
            </AppButton>
          </td>
        </tr>
      </tbody>
    </AppTable>

    <div class="flex flex-wrap items-center justify-between gap-2 text-xs text-secondary">
      <span>{{ pdfQueueSummary }}</span>
      <div class="flex items-center gap-2">
        <span>Page {{ pdfQueuePage }} / {{ pdfQueueTotalPages }}</span>
        <AppButton variant="ghost" :disabled="!pdfQueueHasPrev" @click="onPdfQueuePrevPage">Prev</AppButton>
        <AppButton variant="ghost" :disabled="!pdfQueueHasNext" @click="onPdfQueueNextPage">Next</AppButton>
      </div>
    </div>
  </AppCard>
  </section>
</template>
