<script setup lang="ts">
import { ref } from "vue";
import AppBadge from "@/components/ui/AppBadge.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppRefreshButton from "@/components/ui/AppRefreshButton.vue";
import AppTable from "@/components/ui/AppTable.vue";
import {
  getAdminDbIntegrityReport,
  type AdminDbIntegrityCheck,
  type AdminDbIntegrityReport,
} from "@/features/admin_dbops";

const refreshingIntegrity = ref(false);
const integrityReport = ref<AdminDbIntegrityReport | null>(null);

function formatTimestamp(value: string | null): string {
  if (!value) return "n/a";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function statusTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "ok" || status === "completed" || status === "resolved") return "success";
  if (status === "warning" || status === "running" || status === "queued") return "warning";
  if (status === "failed") return "danger";
  return "info";
}

function checkTone(check: AdminDbIntegrityCheck): "warning" | "danger" | "neutral" | "info" {
  if (check.severity === "metric") return "info";
  if (check.count <= 0) return "neutral";
  return check.severity === "failure" ? "danger" : "warning";
}

async function refreshIntegrity(): Promise<void> {
  refreshingIntegrity.value = true;
  try {
    integrityReport.value = await getAdminDbIntegrityReport();
  } finally {
    refreshingIntegrity.value = false;
  }
}

async function load(): Promise<void> {
  await refreshIntegrity();
}

defineExpose({ load });
</script>

<template>
  <AppCard class="space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-1">
        <h2 class="text-lg font-semibold text-ink-primary">Integrity Report</h2>
        <AppHelpHint text="Read-only checks for known corruption patterns and data drift." />
      </div>
      <AppRefreshButton variant="secondary" :loading="refreshingIntegrity" title="Refresh integrity report" loading-title="Refreshing integrity report" @click="refreshIntegrity" />
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
</template>
