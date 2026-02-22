<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import AsyncStateGate from "@/components/patterns/AsyncStateGate.vue";
import RequestStateAlerts from "@/components/patterns/RequestStateAlerts.vue";
import AppBadge from "@/components/ui/AppBadge.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppCheckbox from "@/components/ui/AppCheckbox.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppModal from "@/components/ui/AppModal.vue";
import AppRefreshButton from "@/components/ui/AppRefreshButton.vue";
import AppSelect from "@/components/ui/AppSelect.vue";
import AppTable from "@/components/ui/AppTable.vue";
import {
  getAdminDbIntegrityReport,
  listAdminDbRepairJobs,
  listAdminPdfQueue,
  requeueAdminPdfLookup,
  requeueAllAdminPdfLookups,
  triggerPublicationLinkRepair,
  type AdminDbIntegrityCheck,
  type AdminDbIntegrityReport,
  type AdminDbRepairJob,
  type AdminPdfQueueItem,
  type TriggerPublicationLinkRepairResult,
} from "@/features/admin_dbops";
import {
  createAdminUser,
  listAdminUsers,
  resetAdminUserPassword,
  setAdminUserActive,
  type AdminUser,
} from "@/features/admin_users";
import { ApiRequestError } from "@/lib/api/errors";

const SECTION_USERS = "users";
const SECTION_INTEGRITY = "integrity";
const SECTION_REPAIRS = "repairs";
const SECTION_PDF = "pdf";
const SCOPE_SINGLE_USER = "single_user";
const SCOPE_ALL_USERS = "all_users";
const APPLY_ALL_USERS_CONFIRM_TEXT = "REPAIR ALL USERS";

type RepairScopeMode = typeof SCOPE_SINGLE_USER | typeof SCOPE_ALL_USERS;

const props = defineProps<{
  section: "users" | "integrity" | "repairs" | "pdf";
}>();

const loading = ref(true);
const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);

const refreshingUsers = ref(false);
const creating = ref(false);
const togglingUserId = ref<number | null>(null);
const resettingPassword = ref(false);

const users = ref<AdminUser[]>([]);
const email = ref("");
const password = ref("");
const createIsAdmin = ref(false);
const activeUserId = ref<number | null>(null);
const resetPassword = ref("");

const refreshingIntegrity = ref(false);
const integrityReport = ref<AdminDbIntegrityReport | null>(null);

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

const activeUser = computed(() => users.value.find((user) => user.id === activeUserId.value) ?? null);
const typedConfirmationRequired = computed(
  () => repairScopeMode.value === SCOPE_ALL_USERS && !repairDryRun.value,
);
const pdfQueuePageSizeValue = computed(() => {
  const parsed = Number(pdfQueuePageSize.value);
  if (!Number.isFinite(parsed)) {
    return 50;
  }
  return Math.max(1, Math.min(500, Math.trunc(parsed)));
});
const pdfQueueTotalPages = computed(() =>
  Math.max(1, Math.ceil(pdfQueueTotalCount.value / Math.max(pdfQueuePageSizeValue.value, 1))),
);
const pdfQueueSummary = computed(() =>
  `${pdfQueueTotalCount.value} item${pdfQueueTotalCount.value === 1 ? "" : "s"} total`,
);

function clearAlerts(): void {
  errorMessage.value = null;
  errorRequestId.value = null;
  successMessage.value = null;
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "n/a";
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function statusTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "ok" || status === "completed" || status === "resolved") {
    return "success";
  }
  if (status === "warning" || status === "running" || status === "queued") {
    return "warning";
  }
  if (status === "failed") {
    return "danger";
  }
  return "info";
}

function checkTone(check: AdminDbIntegrityCheck): "warning" | "danger" | "neutral" | "info" {
  if (check.severity === "metric") {
    return "info";
  }
  if (check.count <= 0) {
    return "neutral";
  }
  return check.severity === "failure" ? "danger" : "warning";
}

function userRoleLabel(user: AdminUser): string {
  return user.is_admin ? "Admin" : "User";
}

function canRequeuePdf(item: AdminPdfQueueItem): boolean {
  return item.status !== "queued" && item.status !== "running";
}

function statusDotClass(user: AdminUser): string {
  return user.is_active ? "bg-success-500 ring-success-200" : "bg-ink-muted/70 ring-stroke-default";
}

function assignError(error: unknown, fallback: string): void {
  if (error instanceof ApiRequestError) {
    errorMessage.value = error.message;
    errorRequestId.value = error.requestId;
    return;
  }
  if (error instanceof Error && error.message) {
    errorMessage.value = error.message;
    return;
  }
  errorMessage.value = fallback;
}

function parseScholarIds(raw: string): number[] {
  const tokens = raw
    .split(/[,\s]+/)
    .map((token) => token.trim())
    .filter((token) => token.length > 0);
  const deduped = new Set<number>();
  for (const token of tokens) {
    const parsed = Number(token);
    if (!Number.isInteger(parsed) || parsed < 1) {
      throw new Error("Scholar profile IDs must be positive integers.");
    }
    deduped.add(parsed);
  }
  return [...deduped];
}

function parseRepairUserIdOrThrow(raw: string): number {
  const parsed = Number((raw || "").trim());
  if (!Number.isInteger(parsed) || parsed < 1) {
    throw new Error("Select a valid target user.");
  }
  return parsed;
}

function validateTypedConfirmation(): string {
  const normalized = repairConfirmationText.value.trim();
  if (typedConfirmationRequired.value && normalized !== APPLY_ALL_USERS_CONFIRM_TEXT) {
    throw new Error(`Type '${APPLY_ALL_USERS_CONFIRM_TEXT}' to apply repair for all users.`);
  }
  return normalized;
}

function summaryCount(job: AdminDbRepairJob, key: string): string {
  const value = job.summary[key];
  return typeof value === "number" ? String(value) : "n/a";
}

function openUserModal(user: AdminUser): void {
  activeUserId.value = user.id;
  resetPassword.value = "";
}

function closeUserModal(): void {
  activeUserId.value = null;
  resetPassword.value = "";
}

function ensureRepairUserSelected(): void {
  if (repairScopeMode.value !== SCOPE_SINGLE_USER || repairUserId.value || users.value.length === 0) {
    return;
  }
  repairUserId.value = String(users.value[0].id);
}

async function refreshUsers(): Promise<void> {
  refreshingUsers.value = true;
  try {
    users.value = await listAdminUsers();
    ensureRepairUserSelected();
    if (activeUserId.value !== null && !users.value.some((item) => item.id === activeUserId.value)) {
      closeUserModal();
    }
  } finally {
    refreshingUsers.value = false;
  }
}

async function refreshIntegrity(): Promise<void> {
  refreshingIntegrity.value = true;
  try {
    integrityReport.value = await getAdminDbIntegrityReport();
  } finally {
    refreshingIntegrity.value = false;
  }
}

async function refreshRepairJobs(): Promise<void> {
  refreshingJobs.value = true;
  try {
    repairJobs.value = await listAdminDbRepairJobs(30);
  } finally {
    refreshingJobs.value = false;
  }
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

async function refreshForSection(): Promise<void> {
  if (props.section === SECTION_USERS) {
    await refreshUsers();
    return;
  }
  if (props.section === SECTION_INTEGRITY) {
    await refreshIntegrity();
    return;
  }
  if (props.section === SECTION_REPAIRS) {
    await Promise.all([refreshUsers(), refreshRepairJobs()]);
    return;
  }
  await refreshPdfQueue();
}

async function onCreateUser(): Promise<void> {
  creating.value = true;
  clearAlerts();
  try {
    if (!email.value.trim() || !password.value) {
      throw new Error("Email and password are required.");
    }
    const created = await createAdminUser({
      email: email.value.trim(),
      password: password.value,
      is_admin: createIsAdmin.value,
    });
    email.value = "";
    password.value = "";
    createIsAdmin.value = false;
    successMessage.value = `User created: ${created.email}`;
    await refreshUsers();
  } catch (error) {
    assignError(error, "Unable to create user.");
  } finally {
    creating.value = false;
  }
}

async function onToggleUser(user: AdminUser): Promise<void> {
  togglingUserId.value = user.id;
  clearAlerts();
  try {
    const updated = await setAdminUserActive(user.id, !user.is_active);
    successMessage.value = `${updated.email} is now ${updated.is_active ? "active" : "inactive"}.`;
    await refreshUsers();
  } catch (error) {
    assignError(error, "Unable to update user.");
  } finally {
    togglingUserId.value = null;
  }
}

async function onResetPassword(): Promise<void> {
  const user = activeUser.value;
  if (!user) {
    return;
  }
  resettingPassword.value = true;
  clearAlerts();
  try {
    const candidate = resetPassword.value.trim();
    if (candidate.length < 12) {
      throw new Error("New password must be at least 12 characters.");
    }
    const result = await resetAdminUserPassword(user.id, candidate);
    resetPassword.value = "";
    successMessage.value = result.message || `Password reset for ${user.email}.`;
  } catch (error) {
    assignError(error, "Unable to reset password.");
  } finally {
    resettingPassword.value = false;
  }
}

async function onRunRepair(): Promise<void> {
  runningRepair.value = true;
  clearAlerts();
  try {
    const scopeMode = repairScopeMode.value;
    const payload = {
      scope_mode: scopeMode,
      scholar_profile_ids: parseScholarIds(repairScholarIds.value),
      dry_run: repairDryRun.value,
      gc_orphan_publications: repairGcOrphans.value,
      requested_by: repairRequestedBy.value.trim() || undefined,
      confirmation_text: validateTypedConfirmation() || undefined,
      user_id: scopeMode === SCOPE_SINGLE_USER ? parseRepairUserIdOrThrow(repairUserId.value) : undefined,
    };
    const result = await triggerPublicationLinkRepair(payload);
    lastRepairResult.value = result;
    successMessage.value = `Repair job #${result.job_id} completed (${result.status}).`;
    repairConfirmationText.value = "";
    await Promise.all([refreshIntegrity(), refreshRepairJobs(), refreshPdfQueue()]);
  } catch (error) {
    assignError(error, "Unable to run publication link repair.");
  } finally {
    runningRepair.value = false;
  }
}

function onScopeModeChange(): void {
  ensureRepairUserSelected();
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
  if (!pdfQueueHasPrev.value || pdfQueuePage.value <= 1) {
    return;
  }
  pdfQueuePage.value = Math.max(pdfQueuePage.value - 1, 1);
  await refreshPdfQueue();
}

async function onPdfQueueNextPage(): Promise<void> {
  if (!pdfQueueHasNext.value) {
    return;
  }
  pdfQueuePage.value += 1;
  await refreshPdfQueue();
}

async function onRequeuePdf(item: AdminPdfQueueItem): Promise<void> {
  requeueingPublicationId.value = item.publication_id;
  clearAlerts();
  try {
    const result = await requeueAdminPdfLookup(item.publication_id);
    successMessage.value = result.message;
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
    successMessage.value = result.message;
    await refreshPdfQueue();
  } catch (error) {
    assignError(error, "Unable to queue missing PDF lookups.");
  } finally {
    requeueingAllPdfs.value = false;
  }
}

onMounted(async () => {
  loading.value = true;
  clearAlerts();
  try {
    await refreshForSection();
  } catch (error) {
    assignError(error, "Unable to load admin data.");
  } finally {
    loading.value = false;
  }
});

watch(
  () => props.section,
  async () => {
    loading.value = true;
    clearAlerts();
    try {
      await refreshForSection();
    } catch (error) {
      assignError(error, "Unable to load admin data.");
    } finally {
      loading.value = false;
    }
  },
);
</script>

<template>
  <section class="grid gap-4">
    <RequestStateAlerts
      :success-message="successMessage"
      :error-message="errorMessage"
      :error-request-id="errorRequestId"
      success-title="Operation complete"
      error-title="Operation failed"
      @dismiss-success="successMessage = null"
    />

    <AsyncStateGate :loading="loading" :loading-lines="10" :show-empty="false">
      <AppCard v-if="props.section === SECTION_USERS" class="space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="flex items-center gap-1">
            <h2 class="text-lg font-semibold text-ink-primary">Users</h2>
            <AppHelpHint text="Create accounts, toggle active status, and reset passwords." />
          </div>
          <AppRefreshButton
            variant="secondary"
            :loading="refreshingUsers"
            title="Refresh users"
            loading-title="Refreshing users"
            @click="refreshUsers"
          />
        </div>

        <form class="grid gap-3 md:grid-cols-3" @submit.prevent="onCreateUser">
          <label class="grid gap-1 text-sm font-medium text-ink-secondary">
            <span>Email</span>
            <AppInput v-model="email" type="email" autocomplete="off" />
          </label>
          <label class="grid gap-1 text-sm font-medium text-ink-secondary">
            <span>Password</span>
            <AppInput v-model="password" type="password" autocomplete="new-password" />
          </label>
          <div class="grid gap-2 text-sm font-medium text-ink-secondary">
            <span>Role</span>
            <div class="flex items-center gap-3">
              <AppCheckbox id="admin-create-user-is-admin" v-model="createIsAdmin" label="Grant admin" />
              <AppButton type="submit" :disabled="creating">
                {{ creating ? "Creating..." : "Create user" }}
              </AppButton>
            </div>
          </div>
        </form>

        <AppTable label="Users table">
          <thead>
            <tr>
              <th scope="col">Email</th>
              <th scope="col">Role</th>
              <th scope="col">Status</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td class="align-middle">
                <button
                  type="button"
                  class="group inline-flex items-center gap-2 rounded-md px-1 py-0.5 text-left text-ink-primary transition hover:bg-surface-card-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset"
                  @click="openUserModal(user)"
                >
                  <span
                    :class="statusDotClass(user)"
                    class="h-2.5 w-2.5 rounded-full ring-2"
                    :aria-label="user.is_active ? 'Active user' : 'Inactive user'"
                  />
                  <span class="underline-offset-2 group-hover:underline">{{ user.email }}</span>
                </button>
              </td>
              <td>{{ userRoleLabel(user) }}</td>
              <td>{{ user.is_active ? "active" : "inactive" }}</td>
              <td class="flex flex-wrap items-center gap-2">
                <AppButton variant="secondary" :disabled="togglingUserId === user.id" @click="onToggleUser(user)">
                  {{ togglingUserId === user.id ? "Updating..." : user.is_active ? "Deactivate" : "Activate" }}
                </AppButton>
                <AppButton variant="ghost" @click="openUserModal(user)">Manage</AppButton>
              </td>
            </tr>
          </tbody>
        </AppTable>
      </AppCard>

      <AppCard v-if="props.section === SECTION_INTEGRITY" class="space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="flex items-center gap-1">
            <h2 class="text-lg font-semibold text-ink-primary">Integrity Report</h2>
            <AppHelpHint text="Read-only checks for known corruption patterns and data drift." />
          </div>
          <AppRefreshButton
            variant="secondary"
            :loading="refreshingIntegrity"
            title="Refresh integrity report"
            loading-title="Refreshing integrity report"
            @click="refreshIntegrity"
          />
        </div>

        <div v-if="integrityReport" class="flex flex-wrap items-center gap-2 text-xs">
          <AppBadge :tone="statusTone(integrityReport.status)">Status: {{ integrityReport.status }}</AppBadge>
          <AppBadge tone="warning">Warnings: {{ integrityReport.warnings.length }}</AppBadge>
          <AppBadge tone="danger">Failures: {{ integrityReport.failures.length }}</AppBadge>
          <span class="text-secondary">Checked: {{ formatTimestamp(integrityReport.checked_at) }}</span>
        </div>

        <AppTable v-if="integrityReport" label="Integrity checks">
          <thead>
            <tr>
              <th scope="col">Check</th>
              <th scope="col">Count</th>
              <th scope="col">Severity</th>
              <th scope="col">Message</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="check in integrityReport.checks" :key="check.name">
              <td>{{ check.name }}</td>
              <td>{{ check.count }}</td>
              <td><AppBadge :tone="checkTone(check)">{{ check.severity }}</AppBadge></td>
              <td>{{ check.message }}</td>
            </tr>
          </tbody>
        </AppTable>
      </AppCard>

      <section v-if="props.section === SECTION_REPAIRS" class="grid gap-4">
        <AppCard class="space-y-3">
          <div class="flex items-center gap-1">
            <h2 class="text-lg font-semibold text-ink-primary">Publication Link Repair</h2>
            <AppHelpHint text="Dry-run first. For all-users apply mode, typed confirmation is required." />
          </div>

          <form class="grid gap-3 md:grid-cols-2" @submit.prevent="onRunRepair">
            <label class="grid gap-1 text-sm font-medium text-ink-secondary">
              <span>Scope</span>
              <AppSelect v-model="repairScopeMode" @change="onScopeModeChange">
                <option :value="SCOPE_SINGLE_USER">Single user</option>
                <option :value="SCOPE_ALL_USERS">All users</option>
              </AppSelect>
            </label>
            <label class="grid gap-1 text-sm font-medium text-ink-secondary">
              <span>Target user</span>
              <AppSelect v-model="repairUserId" :disabled="repairScopeMode === SCOPE_ALL_USERS || users.length === 0">
                <option value="" disabled>Select user</option>
                <option v-for="user in users" :key="user.id" :value="String(user.id)">
                  {{ user.email }} (ID {{ user.id }})
                </option>
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
            <p v-if="repairScopeMode === SCOPE_ALL_USERS" class="text-xs text-secondary md:col-span-2">
              All-users scope includes every scholar profile across all accounts.
            </p>
            <div class="md:col-span-2">
              <AppButton type="submit" :disabled="runningRepair">
                {{ runningRepair ? "Running..." : "Run repair job" }}
              </AppButton>
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
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex items-center gap-1">
              <h2 class="text-lg font-semibold text-ink-primary">Recent Repair Jobs</h2>
              <AppHelpHint text="Audit history and summary counters for each repair job." />
            </div>
            <AppRefreshButton
              variant="secondary"
              :loading="refreshingJobs"
              title="Refresh repair jobs"
              loading-title="Refreshing repair jobs"
              @click="refreshRepairJobs"
            />
          </div>
          <AppTable label="Repair jobs table">
            <thead>
              <tr>
                <th scope="col">Job</th>
                <th scope="col">Status</th>
                <th scope="col">Mode</th>
                <th scope="col">Requested by</th>
                <th scope="col">Created</th>
                <th scope="col">Links in scope</th>
                <th scope="col">Links deleted</th>
              </tr>
            </thead>
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
      </section>

      <AppCard v-if="props.section === SECTION_PDF" class="space-y-3">
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
            <AppButton
              variant="secondary"
              class="!min-h-8 whitespace-nowrap !px-2.5 !py-1 !text-xs"
              :disabled="requeueingAllPdfs"
              title="Queue all missing PDFs"
              @click="onRequeueAllPdfs"
            >
              {{ requeueingAllPdfs ? "Queueing..." : "Queue all" }}
            </AppButton>
            <AppRefreshButton
              variant="secondary"
              size="sm"
              :loading="refreshingPdfQueue"
              title="Refresh PDF queue"
              loading-title="Refreshing PDF queue"
              @click="refreshPdfQueue"
            />
          </div>
        </div>

        <AppTable label="PDF queue table">
          <thead>
            <tr>
              <th scope="col">Publication</th>
              <th scope="col">Status</th>
              <th scope="col">Attempts</th>
              <th scope="col">Failure reason</th>
              <th scope="col">Source</th>
              <th scope="col">Requested by</th>
              <th scope="col">Queued</th>
              <th scope="col">Last attempt</th>
              <th scope="col">Resolved</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in pdfQueueItems" :key="item.publication_id">
              <td>
                <div class="grid gap-1">
                  <span class="font-medium text-ink-primary">{{ item.title }}</span>
                  <a
                    v-if="item.display_identifier?.url"
                    :href="item.display_identifier.url"
                    target="_blank"
                    rel="noreferrer"
                    class="link-inline text-xs"
                  >
                    {{ item.display_identifier.label }}
                  </a>
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
                <AppButton
                  variant="ghost"
                  :disabled="requeueingPublicationId === item.publication_id || !canRequeuePdf(item)"
                  @click="onRequeuePdf(item)"
                >
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
    </AsyncStateGate>

    <AppModal :open="activeUser !== null" title="User settings" @close="closeUserModal">
      <div v-if="activeUser" class="grid gap-4">
        <div class="space-y-1">
          <div class="flex items-center gap-2">
            <span
              :class="statusDotClass(activeUser)"
              class="h-2.5 w-2.5 rounded-full ring-2"
              :aria-label="activeUser.is_active ? 'Active user' : 'Inactive user'"
            />
            <p class="truncate text-sm font-semibold text-ink-primary">{{ activeUser.email }}</p>
          </div>
          <p class="text-sm text-secondary">Role: {{ userRoleLabel(activeUser) }}</p>
          <p class="text-xs text-secondary">Last updated: {{ formatTimestamp(activeUser.updated_at) }}</p>
        </div>

        <div class="grid gap-2">
          <label class="grid gap-1 text-sm font-medium text-ink-secondary">
            <span>New password</span>
            <AppInput
              id="admin-reset-password"
              v-model="resetPassword"
              type="password"
              autocomplete="new-password"
              placeholder="At least 12 characters"
            />
          </label>
          <div class="flex flex-wrap gap-2">
            <AppButton :disabled="resettingPassword" @click="onResetPassword">
              {{ resettingPassword ? "Resetting..." : "Reset password" }}
            </AppButton>
            <AppButton variant="secondary" :disabled="togglingUserId === activeUser.id" @click="onToggleUser(activeUser)">
              {{ togglingUserId === activeUser.id ? "Updating..." : activeUser.is_active ? "Deactivate user" : "Activate user" }}
            </AppButton>
          </div>
        </div>
      </div>
    </AppModal>
  </section>
</template>
