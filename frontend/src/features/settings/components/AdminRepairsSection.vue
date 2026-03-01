<script setup lang="ts">
import { computed, ref } from "vue";
import AppBadge from "@/components/ui/AppBadge.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppCheckbox from "@/components/ui/AppCheckbox.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppRefreshButton from "@/components/ui/AppRefreshButton.vue";
import AppSelect from "@/components/ui/AppSelect.vue";
import AppTable from "@/components/ui/AppTable.vue";
import {
  dropAllPublications,
  listAdminDbRepairJobs,
  triggerPublicationLinkRepair,
  triggerPublicationNearDuplicateRepair,
  type AdminDbRepairJob,
  type NearDuplicateCluster,
  type TriggerPublicationLinkRepairResult,
  type TriggerPublicationNearDuplicateRepairResult,
} from "@/features/admin_dbops";
import type { AdminUser } from "@/features/admin_users";
import { useRequestState } from "@/composables/useRequestState";

const props = defineProps<{
  users: AdminUser[];
}>();

const SCOPE_SINGLE_USER = "single_user";
const SCOPE_ALL_USERS = "all_users";
const APPLY_ALL_USERS_CONFIRM_TEXT = "REPAIR ALL USERS";
const APPLY_NEAR_DUPLICATES_CONFIRM_TEXT = "MERGE SELECTED DUPLICATES";
const DROP_PUBLICATIONS_CONFIRM_TEXT = "DROP ALL PUBLICATIONS";

type RepairScopeMode = typeof SCOPE_SINGLE_USER | typeof SCOPE_ALL_USERS;

const { clearAlerts, assignError, setSuccess } = useRequestState();

const refreshingJobs = ref(false);
const runningRepair = ref(false);
const repairJobs = ref<AdminDbRepairJob[]>([]);
const lastRepairResult = ref<TriggerPublicationLinkRepairResult | null>(null);
const repairScopeMode = ref<RepairScopeMode>(SCOPE_SINGLE_USER);
const repairUserId = ref("");
const repairScholarIds = ref("");
const repairRequestedBy = ref("");
const repairDryRun = ref(true);
const repairGcOrphans = ref(false);
const repairConfirmationText = ref("");

const runningNearDuplicateScan = ref(false);
const applyingNearDuplicateRepair = ref(false);
const nearDuplicateRequestedBy = ref("");
const nearDuplicateSimilarityThreshold = ref("0.78");
const nearDuplicateMinSharedTokens = ref("3");
const nearDuplicateMaxYearDelta = ref("1");
const nearDuplicateMaxClusters = ref("25");
const nearDuplicateConfirmationText = ref("");
const nearDuplicateSelectedClusterKeys = ref<Set<string>>(new Set());
const nearDuplicateClusters = ref<NearDuplicateCluster[]>([]);
const lastNearDuplicateResult = ref<TriggerPublicationNearDuplicateRepairResult | null>(null);

const droppingPublications = ref(false);
const dropConfirmationText = ref("");
const dropResult = ref<{ deleted_count: number; message: string } | null>(null);
const dropConfirmationValid = computed(() => dropConfirmationText.value.trim() === DROP_PUBLICATIONS_CONFIRM_TEXT);

const typedConfirmationRequired = computed(
  () => repairScopeMode.value === SCOPE_ALL_USERS && !repairDryRun.value,
);
const nearDuplicateApplyEnabled = computed(() => nearDuplicateSelectedClusterKeys.value.size > 0);

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

function parseScholarIds(raw: string): number[] {
  const tokens = raw.split(/[,\s]+/).map((t) => t.trim()).filter((t) => t.length > 0);
  const deduped = new Set<number>();
  for (const token of tokens) {
    const parsed = Number(token);
    if (!Number.isInteger(parsed) || parsed < 1) throw new Error("Scholar profile IDs must be positive integers.");
    deduped.add(parsed);
  }
  return [...deduped];
}

function parseRepairUserIdOrThrow(raw: string): number {
  const parsed = Number((raw || "").trim());
  if (!Number.isInteger(parsed) || parsed < 1) throw new Error("Select a valid target user.");
  return parsed;
}

function validateTypedConfirmation(): string {
  const normalized = repairConfirmationText.value.trim();
  if (typedConfirmationRequired.value && normalized !== APPLY_ALL_USERS_CONFIRM_TEXT) {
    throw new Error(`Type '${APPLY_ALL_USERS_CONFIRM_TEXT}' to apply repair for all users.`);
  }
  return normalized;
}

function parseBoundedNumber(raw: string, opts: { minimum: number; maximum: number; fallback: number }): number {
  const parsed = Number(raw.trim());
  if (!Number.isFinite(parsed)) return opts.fallback;
  return Math.max(opts.minimum, Math.min(opts.maximum, parsed));
}

function nearDuplicatePayloadBase() {
  return {
    similarity_threshold: parseBoundedNumber(nearDuplicateSimilarityThreshold.value, { minimum: 0.5, maximum: 1.0, fallback: 0.78 }),
    min_shared_tokens: Math.trunc(parseBoundedNumber(nearDuplicateMinSharedTokens.value, { minimum: 1, maximum: 8, fallback: 3 })),
    max_year_delta: Math.trunc(parseBoundedNumber(nearDuplicateMaxYearDelta.value, { minimum: 0, maximum: 5, fallback: 1 })),
    max_clusters: Math.trunc(parseBoundedNumber(nearDuplicateMaxClusters.value, { minimum: 1, maximum: 200, fallback: 25 })),
    requested_by: nearDuplicateRequestedBy.value.trim() || undefined,
  };
}

function checkboxEventChecked(event: Event): boolean {
  return event.target instanceof HTMLInputElement ? event.target.checked : false;
}

function summaryCount(job: AdminDbRepairJob, key: string): string {
  const value = job.summary[key];
  return typeof value === "number" ? String(value) : "n/a";
}

function ensureRepairUserSelected(): void {
  if (repairScopeMode.value !== SCOPE_SINGLE_USER || repairUserId.value || props.users.length === 0) return;
  repairUserId.value = String(props.users[0].id);
}

async function refreshRepairJobs(): Promise<void> {
  refreshingJobs.value = true;
  try { repairJobs.value = await listAdminDbRepairJobs(30); } finally { refreshingJobs.value = false; }
}

async function onRunRepair(): Promise<void> {
  runningRepair.value = true;
  clearAlerts();
  try {
    const payload = {
      scope_mode: repairScopeMode.value,
      scholar_profile_ids: parseScholarIds(repairScholarIds.value),
      dry_run: repairDryRun.value,
      gc_orphan_publications: repairGcOrphans.value,
      requested_by: repairRequestedBy.value.trim() || undefined,
      confirmation_text: validateTypedConfirmation() || undefined,
      user_id: repairScopeMode.value === SCOPE_SINGLE_USER ? parseRepairUserIdOrThrow(repairUserId.value) : undefined,
    };
    const result = await triggerPublicationLinkRepair(payload);
    lastRepairResult.value = result;
    setSuccess(`Repair job #${result.job_id} completed (${result.status}).`);
    repairConfirmationText.value = "";
    await refreshRepairJobs();
  } catch (error) {
    assignError(error, "Unable to run publication link repair.");
  } finally {
    runningRepair.value = false;
  }
}

function onToggleNearDuplicateClusterSelection(clusterKey: string, checked: boolean): void {
  const next = new Set(nearDuplicateSelectedClusterKeys.value);
  if (checked) { next.add(clusterKey); } else { next.delete(clusterKey); }
  nearDuplicateSelectedClusterKeys.value = next;
}

async function onRunNearDuplicateScan(): Promise<void> {
  runningNearDuplicateScan.value = true;
  clearAlerts();
  try {
    const result = await triggerPublicationNearDuplicateRepair({ dry_run: true, ...nearDuplicatePayloadBase() });
    nearDuplicateClusters.value = result.clusters;
    nearDuplicateSelectedClusterKeys.value = new Set();
    nearDuplicateConfirmationText.value = "";
    lastNearDuplicateResult.value = result;
    setSuccess(`Near-duplicate scan completed (job #${result.job_id}).`);
    await refreshRepairJobs();
  } catch (error) {
    assignError(error, "Unable to scan for near-duplicate publications.");
  } finally {
    runningNearDuplicateScan.value = false;
  }
}

async function onApplyNearDuplicateRepair(): Promise<void> {
  applyingNearDuplicateRepair.value = true;
  clearAlerts();
  try {
    const selectedKeys = [...nearDuplicateSelectedClusterKeys.value].sort((a, b) => a.localeCompare(b));
    if (selectedKeys.length === 0) throw new Error("Select at least one near-duplicate cluster before applying.");
    if (nearDuplicateConfirmationText.value.trim() !== APPLY_NEAR_DUPLICATES_CONFIRM_TEXT) {
      throw new Error(`Type '${APPLY_NEAR_DUPLICATES_CONFIRM_TEXT}' to confirm merge.`);
    }
    const result = await triggerPublicationNearDuplicateRepair({
      dry_run: false,
      selected_cluster_keys: selectedKeys,
      confirmation_text: nearDuplicateConfirmationText.value.trim(),
      ...nearDuplicatePayloadBase(),
    });
    nearDuplicateClusters.value = result.clusters;
    nearDuplicateSelectedClusterKeys.value = new Set();
    nearDuplicateConfirmationText.value = "";
    lastNearDuplicateResult.value = result;
    setSuccess(`Merged selected near-duplicate clusters (job #${result.job_id}).`);
    await refreshRepairJobs();
  } catch (error) {
    assignError(error, "Unable to apply near-duplicate merge.");
  } finally {
    applyingNearDuplicateRepair.value = false;
  }
}

async function onDropAllPublications(): Promise<void> {
  droppingPublications.value = true;
  clearAlerts();
  dropResult.value = null;
  try {
    const result = await dropAllPublications(dropConfirmationText.value.trim());
    dropResult.value = result;
    setSuccess(result.message);
    dropConfirmationText.value = "";
  } catch (error) {
    assignError(error, "Unable to drop publications.");
  } finally {
    droppingPublications.value = false;
  }
}

async function load(): Promise<void> {
  await refreshRepairJobs();
  ensureRepairUserSelected();
}

defineExpose({ load });
</script>

<template>
  <section class="grid gap-4">
    <AppCard class="space-y-3">
      <div class="flex items-center gap-1">
        <h2 class="text-lg font-semibold text-ink-primary">Publication Link Repair</h2>
        <AppHelpHint text="Dry-run first. For all-users apply mode, typed confirmation is required." />
      </div>
      <form class="grid gap-3 md:grid-cols-2" @submit.prevent="onRunRepair">
        <label class="grid gap-1 text-sm font-medium text-ink-secondary">
          <span>Scope</span>
          <AppSelect v-model="repairScopeMode" @change="ensureRepairUserSelected">
            <option :value="SCOPE_SINGLE_USER">Single user</option>
            <option :value="SCOPE_ALL_USERS">All users</option>
          </AppSelect>
        </label>
        <label class="grid gap-1 text-sm font-medium text-ink-secondary">
          <span>Target user</span>
          <AppSelect v-model="repairUserId" :disabled="repairScopeMode === SCOPE_ALL_USERS || users.length === 0">
            <option value="" disabled>Select user</option>
            <option v-for="user in users" :key="user.id" :value="String(user.id)">{{ user.email }} (ID {{ user.id }})</option>
          </AppSelect>
        </label>
        <label class="grid gap-1 text-sm font-medium text-ink-secondary md:col-span-2">
          <span>Scholar profile IDs (optional)</span>
          <AppInput v-model="repairScholarIds" placeholder="e.g. 12,13,14" />
        </label>
        <label class="grid gap-1 text-sm font-medium text-ink-secondary md:col-span-2">
          <span>Requested by (optional)</span>
          <AppInput v-model="repairRequestedBy" placeholder="email/name/ticket id" />
        </label>
        <div class="flex flex-wrap items-center gap-4 md:col-span-2">
          <AppCheckbox id="repair-dry-run" v-model="repairDryRun" label="Dry-run (no writes)" />
          <AppCheckbox id="repair-gc-orphans" v-model="repairGcOrphans" label="Delete orphan publications" />
        </div>
        <label v-if="typedConfirmationRequired" class="grid gap-1 text-sm font-medium text-ink-secondary md:col-span-2">
          <span>Type '{{ APPLY_ALL_USERS_CONFIRM_TEXT }}' to confirm</span>
          <AppInput v-model="repairConfirmationText" :placeholder="APPLY_ALL_USERS_CONFIRM_TEXT" />
        </label>
        <p v-if="repairScopeMode === SCOPE_ALL_USERS" class="text-xs text-secondary md:col-span-2">All-users scope includes every scholar profile across all accounts.</p>
        <div class="md:col-span-2">
          <AppButton type="submit" :disabled="runningRepair">{{ runningRepair ? "Running..." : "Run repair job" }}</AppButton>
        </div>
      </form>
      <div v-if="lastRepairResult" class="rounded-lg border border-stroke-default bg-surface-card-muted p-3 text-xs">
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <AppBadge :tone="statusTone(lastRepairResult.status)">Job #{{ lastRepairResult.job_id }}</AppBadge>
          <span class="text-secondary">Status: {{ lastRepairResult.status }}</span>
        </div>
        <pre class="overflow-x-auto text-secondary">{{ JSON.stringify(lastRepairResult.summary, null, 2) }}</pre>
      </div>
    </AppCard>

    <AppCard class="space-y-3">
      <div class="flex items-center gap-1">
        <h2 class="text-lg font-semibold text-ink-primary">Near-Duplicate Publication Repair</h2>
        <AppHelpHint text="Run a dry-run scan first, verify candidate clusters, then merge only selected clusters." />
      </div>
      <form class="grid gap-3 md:grid-cols-2" @submit.prevent="onRunNearDuplicateScan">
        <label class="grid gap-1 text-sm font-medium text-ink-secondary"><span>Similarity threshold</span><AppInput v-model="nearDuplicateSimilarityThreshold" placeholder="0.78" /></label>
        <label class="grid gap-1 text-sm font-medium text-ink-secondary"><span>Min shared tokens</span><AppInput v-model="nearDuplicateMinSharedTokens" placeholder="3" /></label>
        <label class="grid gap-1 text-sm font-medium text-ink-secondary"><span>Max year delta</span><AppInput v-model="nearDuplicateMaxYearDelta" placeholder="1" /></label>
        <label class="grid gap-1 text-sm font-medium text-ink-secondary"><span>Max preview clusters</span><AppInput v-model="nearDuplicateMaxClusters" placeholder="25" /></label>
        <label class="grid gap-1 text-sm font-medium text-ink-secondary md:col-span-2"><span>Requested by (optional)</span><AppInput v-model="nearDuplicateRequestedBy" placeholder="email/name/ticket id" /></label>
        <div class="md:col-span-2">
          <AppButton type="submit" :disabled="runningNearDuplicateScan">{{ runningNearDuplicateScan ? "Scanning..." : "Scan near-duplicate clusters" }}</AppButton>
        </div>
      </form>
      <div v-if="nearDuplicateClusters.length > 0" class="space-y-3">
        <AppTable label="Near duplicate clusters table">
          <thead><tr><th scope="col">Select</th><th scope="col">Cluster</th><th scope="col">Winner</th><th scope="col">Members</th><th scope="col">Similarity</th></tr></thead>
          <tbody>
            <tr v-for="cluster in nearDuplicateClusters" :key="cluster.cluster_key">
              <td><input :id="`near-dup-${cluster.cluster_key}`" class="h-4 w-4 rounded border-stroke-default bg-surface-card" type="checkbox" :checked="nearDuplicateSelectedClusterKeys.has(cluster.cluster_key)" @change="onToggleNearDuplicateClusterSelection(cluster.cluster_key, checkboxEventChecked($event))" /></td>
              <td class="font-mono text-xs">{{ cluster.cluster_key }}</td>
              <td>#{{ cluster.winner_publication_id }}</td>
              <td><div class="grid gap-1"><span v-for="member in cluster.members" :key="member.publication_id" class="text-xs text-secondary">#{{ member.publication_id }} · {{ member.title }}</span></div></td>
              <td>{{ cluster.similarity_score.toFixed(2) }}</td>
            </tr>
          </tbody>
        </AppTable>
        <form class="grid gap-3 md:grid-cols-2" @submit.prevent="onApplyNearDuplicateRepair">
          <label class="grid gap-1 text-sm font-medium text-ink-secondary md:col-span-2"><span>Type '{{ APPLY_NEAR_DUPLICATES_CONFIRM_TEXT }}' to merge selected clusters</span><AppInput v-model="nearDuplicateConfirmationText" :placeholder="APPLY_NEAR_DUPLICATES_CONFIRM_TEXT" /></label>
          <div class="md:col-span-2"><AppButton type="submit" :disabled="applyingNearDuplicateRepair || !nearDuplicateApplyEnabled">{{ applyingNearDuplicateRepair ? "Merging..." : "Merge selected clusters" }}</AppButton></div>
        </form>
      </div>
      <div v-if="lastNearDuplicateResult" class="rounded-lg border border-stroke-default bg-surface-card-muted p-3 text-xs">
        <div class="mb-2 flex flex-wrap items-center gap-2"><AppBadge :tone="statusTone(lastNearDuplicateResult.status)">Job #{{ lastNearDuplicateResult.job_id }}</AppBadge><span class="text-secondary">Status: {{ lastNearDuplicateResult.status }}</span></div>
        <pre class="overflow-x-auto text-secondary">{{ JSON.stringify(lastNearDuplicateResult.summary, null, 2) }}</pre>
      </div>
    </AppCard>

    <AppCard class="space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-1"><h2 class="text-lg font-semibold text-ink-primary">Recent Repair Jobs</h2><AppHelpHint text="Audit history and summary counters for each repair job." /></div>
        <AppRefreshButton variant="secondary" :loading="refreshingJobs" title="Refresh repair jobs" loading-title="Refreshing repair jobs" @click="refreshRepairJobs" />
      </div>
      <AppTable label="Repair jobs table">
        <thead><tr><th scope="col">Job</th><th scope="col">Status</th><th scope="col">Mode</th><th scope="col">Requested by</th><th scope="col">Created</th><th scope="col">Links in scope</th><th scope="col">Links deleted</th></tr></thead>
        <tbody>
          <tr v-for="job in repairJobs" :key="job.id">
            <td>#{{ job.id }} · {{ job.job_name }}</td>
            <td><AppBadge :tone="statusTone(job.status)">{{ job.status }}</AppBadge></td>
            <td>{{ job.dry_run ? "dry-run" : "apply" }}</td>
            <td>{{ job.requested_by || "n/a" }}</td>
            <td>{{ formatTimestamp(job.created_at) }}</td>
            <td>{{ summaryCount(job, "links_in_scope") }}</td>
            <td>{{ summaryCount(job, "links_deleted") }}</td>
          </tr>
        </tbody>
      </AppTable>
    </AppCard>

    <AppCard class="space-y-3 border-state-danger-border">
      <div class="flex items-center gap-1"><h2 class="text-lg font-semibold text-state-danger-text">Drop All Publications</h2><AppHelpHint text="Permanently delete ALL publications, links, identifiers, and PDF jobs. Scholar baselines will be reset so the next run re-discovers everything." /></div>
      <p class="text-sm text-secondary">This action is <strong>irreversible</strong>. It deletes every publication record across all users. The next ingestion run will re-populate all data from scratch.</p>
      <form class="grid gap-3" @submit.prevent="onDropAllPublications">
        <label class="grid gap-1 text-sm font-medium text-ink-secondary"><span>Type '{{ DROP_PUBLICATIONS_CONFIRM_TEXT }}' to confirm</span><AppInput v-model="dropConfirmationText" :placeholder="DROP_PUBLICATIONS_CONFIRM_TEXT" autocomplete="off" /></label>
        <div><AppButton type="submit" variant="danger" :disabled="droppingPublications || !dropConfirmationValid">{{ droppingPublications ? "Dropping..." : "Drop all publications" }}</AppButton></div>
      </form>
      <div v-if="dropResult" class="rounded-lg border border-stroke-default bg-surface-card-muted p-3 text-xs">
        <div class="mb-1 flex items-center gap-2"><AppBadge tone="danger">Deleted: {{ dropResult.deleted_count }}</AppBadge></div>
        <p class="text-secondary">{{ dropResult.message }}</p>
      </div>
    </AppCard>
  </section>
</template>
