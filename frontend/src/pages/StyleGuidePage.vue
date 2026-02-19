<script setup lang="ts">
import { computed, ref } from "vue";

import AppPage from "@/components/layout/AppPage.vue";
import QueueHealthBadge from "@/components/patterns/QueueHealthBadge.vue";
import RunStatusBadge from "@/components/patterns/RunStatusBadge.vue";
import AppAlert from "@/components/ui/AppAlert.vue";
import AppBadge from "@/components/ui/AppBadge.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppCheckbox from "@/components/ui/AppCheckbox.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppSelect from "@/components/ui/AppSelect.vue";
import AppTable from "@/components/ui/AppTable.vue";
import { useThemeStore } from "@/stores/theme";

const sampleName = ref("Ada Lovelace");
const sampleEmail = ref("ada@example.com");
const sampleRole = ref("operator");
const sampleEnabled = ref(true);
const theme = useThemeStore();

const isDarkTheme = computed(() => theme.active === "dark");
const toggleThemeLabel = computed(() =>
  isDarkTheme.value ? "Switch to light mode" : "Switch to dark mode",
);
const selectedPreset = computed({
  get: () => theme.preset,
  set: (value: string) => theme.setPreset(value),
});

const surfaceSamples = [
  { label: "App surface", value: "--theme-surface-app" },
  { label: "Nav surface", value: "--theme-surface-nav" },
  { label: "Active nav", value: "--theme-surface-nav-active" },
  { label: "Card surface", value: "--theme-surface-card" },
  { label: "Table header", value: "--theme-surface-table-header" },
  { label: "Input surface", value: "--theme-surface-input" },
];

const textSamples = [
  { label: "Primary text", value: "--theme-text-primary" },
  { label: "Secondary text", value: "--theme-text-secondary" },
  { label: "Muted text", value: "--theme-text-muted" },
  { label: "Inverse text", value: "--theme-text-inverse" },
  { label: "Link text", value: "--theme-text-link" },
];

const actionSamples = [
  { label: "Primary action", value: "--theme-action-primary-bg" },
  { label: "Secondary action", value: "--theme-action-secondary-bg" },
  { label: "Ghost action", value: "--theme-action-ghost-bg" },
  { label: "Danger action", value: "--theme-action-danger-bg" },
];

const borderSamples = [
  { label: "Default border", value: "--theme-border-default" },
  { label: "Strong border", value: "--theme-border-strong" },
  { label: "Subtle border", value: "--theme-border-subtle" },
  { label: "Interactive border", value: "--theme-border-interactive" },
];

const focusSamples = [
  { label: "Focus ring", value: "--theme-focus-ring" },
  { label: "Focus offset", value: "--theme-focus-ring-offset" },
];

const stateSamples = [
  { label: "Info state", value: "--theme-state-info-bg", text: "--theme-state-info-text", border: "--theme-state-info-border" },
  {
    label: "Success state",
    value: "--theme-state-success-bg",
    text: "--theme-state-success-text",
    border: "--theme-state-success-border",
  },
  {
    label: "Warning state",
    value: "--theme-state-warning-bg",
    text: "--theme-state-warning-text",
    border: "--theme-state-warning-border",
  },
  { label: "Danger state", value: "--theme-state-danger-bg", text: "--theme-state-danger-text", border: "--theme-state-danger-border" },
];

const scaleFamilies = ["brand", "info", "success", "warning", "danger"] as const;
const scaleSteps = ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"] as const;

const sampleRows = [
  { id: 101, title: "Entity Resolution Improvements", status: "running", owner: "Scheduler" },
  { id: 102, title: "Retry Queue Drain", status: "partial_failure", owner: "Ops" },
  { id: 103, title: "Weekly Publication Sync", status: "success", owner: "Ingestion" },
];

function cssVarStyle(tokenName: string): Record<string, string> {
  return { backgroundColor: `rgb(var(${tokenName}) / 1)` };
}

function cssVarBorderStyle(tokenName: string): Record<string, string> {
  return { borderColor: `rgb(var(${tokenName}) / 1)` };
}

function textSampleStyle(tokenName: string): Record<string, string> {
  if (tokenName === "--theme-text-inverse") {
    return { backgroundColor: "rgb(var(--theme-surface-overlay) / 1)" };
  }
  return {};
}

function colorScaleStyle(family: (typeof scaleFamilies)[number], step: (typeof scaleSteps)[number]): Record<string, string> {
  return { backgroundColor: `rgb(var(--color-${family}-${step}) / 1)` };
}

function onToggleTheme(): void {
  theme.setPreference(isDarkTheme.value ? "light" : "dark");
}
</script>

<template>
  <AppPage
    title="Style Guide"
    subtitle="Reference page for Tailwind component patterns used across the application."
  >
    <AppCard class="space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="space-y-1">
          <h2 class="text-lg font-semibold text-ink-primary">Theme Lab</h2>
          <p class="text-sm text-secondary">Preview preset + mode behavior and inspect semantic token groups.</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <AppSelect v-model="selectedPreset" class="w-40">
            <option v-for="preset in theme.availablePresets" :key="preset.id" :value="preset.id">
              {{ preset.label }}
            </option>
          </AppSelect>
          <AppButton variant="secondary" @click="onToggleTheme">
            {{ toggleThemeLabel }}
          </AppButton>
        </div>
      </div>

      <div class="grid gap-4 lg:grid-cols-3">
        <div class="space-y-2">
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">Surfaces</p>
          <ul class="grid gap-2">
            <li
              v-for="sample in surfaceSamples"
              :key="sample.value"
              class="flex items-center justify-between rounded-lg border border-stroke-default px-3 py-2 text-xs text-ink-secondary"
              :style="cssVarStyle(sample.value)"
            >
              <span class="font-medium text-ink-primary">{{ sample.label }}</span>
              <code>{{ sample.value }}</code>
            </li>
          </ul>
        </div>

        <div class="space-y-2">
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">Text</p>
          <ul class="grid gap-2">
            <li
              v-for="sample in textSamples"
              :key="sample.value"
              class="flex items-center justify-between rounded-lg border border-stroke-default bg-surface-card px-3 py-2 text-xs"
              :style="textSampleStyle(sample.value)"
            >
              <span class="font-medium" :style="{ color: `rgb(var(${sample.value}) / 1)` }">{{ sample.label }}</span>
              <code class="text-ink-muted">{{ sample.value }}</code>
            </li>
          </ul>
        </div>

        <div class="space-y-2">
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">Actions</p>
          <ul class="grid gap-2">
            <li
              v-for="sample in actionSamples"
              :key="sample.value"
              class="flex items-center justify-between rounded-lg border border-stroke-default px-3 py-2 text-xs text-ink-secondary"
              :style="cssVarStyle(sample.value)"
            >
              <span class="font-medium text-ink-primary">{{ sample.label }}</span>
              <code>{{ sample.value }}</code>
            </li>
          </ul>
        </div>
      </div>

      <div class="grid gap-4 lg:grid-cols-3">
        <div class="space-y-2">
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">Borders</p>
          <ul class="grid gap-2">
            <li
              v-for="sample in borderSamples"
              :key="sample.value"
              class="flex items-center justify-between rounded-lg border-2 bg-surface-card px-3 py-2 text-xs text-ink-secondary"
              :style="cssVarBorderStyle(sample.value)"
            >
              <span class="font-medium text-ink-primary">{{ sample.label }}</span>
              <code>{{ sample.value }}</code>
            </li>
          </ul>
        </div>

        <div class="space-y-2">
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">Focus</p>
          <ul class="grid gap-2">
            <li
              v-for="sample in focusSamples"
              :key="sample.value"
              class="flex items-center justify-between rounded-lg border border-stroke-default bg-surface-card px-3 py-2 text-xs text-ink-secondary"
            >
              <button
                type="button"
                class="rounded-md px-2 py-1 font-medium text-ink-primary focus-visible:ring-2 focus-visible:ring-offset-2"
                :style="{ '--tw-ring-color': `rgb(var(${sample.value}) / 1)`, '--tw-ring-offset-color': 'rgb(var(--theme-focus-ring-offset) / 1)' }"
              >
                Focus me
              </button>
              <code>{{ sample.value }}</code>
            </li>
          </ul>
        </div>

        <div class="space-y-2">
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">States</p>
          <ul class="grid gap-2">
            <li
              v-for="sample in stateSamples"
              :key="sample.value"
              class="flex items-center justify-between rounded-lg border px-3 py-2 text-xs"
              :style="{
                backgroundColor: `rgb(var(${sample.value}) / 1)`,
                borderColor: `rgb(var(${sample.border}) / 1)`,
                color: `rgb(var(${sample.text}) / 1)`,
              }"
            >
              <span class="font-medium">{{ sample.label }}</span>
              <code>{{ sample.value }}</code>
            </li>
          </ul>
        </div>
      </div>
    </AppCard>

    <AppCard class="space-y-4">
      <h2 class="text-lg font-semibold text-ink-primary">Scale Ramps</h2>
      <div class="grid gap-3">
        <div v-for="family in scaleFamilies" :key="family" class="grid gap-1">
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">{{ family }}</p>
          <div class="grid grid-cols-11 gap-1">
            <span
              v-for="step in scaleSteps"
              :key="`${family}-${step}`"
              class="h-8 rounded-md border border-stroke-default"
              :style="colorScaleStyle(family, step)"
              :title="`--color-${family}-${step}`"
            />
          </div>
        </div>
      </div>
    </AppCard>

    <AppCard class="space-y-4">
      <h2 class="text-lg font-semibold text-ink-primary">Shell Preview</h2>
      <p class="text-sm text-secondary">Quick check for app background, nav, card, table, action, and status token coverage.</p>
      <div class="grid gap-3 rounded-2xl border border-stroke-default bg-surface-app p-3 lg:grid-cols-[14rem_minmax(0,1fr)]">
        <aside class="space-y-2 rounded-xl border border-stroke-default bg-surface-nav p-3">
          <div class="rounded-lg bg-surface-nav-active px-2 py-1 text-sm font-semibold text-ink-inverse">Dashboard</div>
          <div class="rounded-lg px-2 py-1 text-sm text-ink-secondary">Publications</div>
          <div class="rounded-lg px-2 py-1 text-sm text-ink-secondary">Scholars</div>
        </aside>
        <section class="space-y-3 rounded-xl border border-stroke-default bg-surface-card p-3">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <p class="text-sm font-semibold text-ink-primary">Latest Update Check</p>
            <RunStatusBadge status="running" />
          </div>
          <div class="flex flex-wrap gap-2">
            <AppButton>Primary action</AppButton>
            <AppButton variant="secondary">Secondary</AppButton>
            <AppBadge tone="warning">Unread</AppBadge>
          </div>
          <AppTable label="Shell preview table">
            <thead>
              <tr>
                <th scope="col">Scholar</th>
                <th scope="col">State</th>
                <th scope="col">Count</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Ada Lovelace</td>
                <td>Checked</td>
                <td>4</td>
              </tr>
              <tr>
                <td>Geoffrey Hinton</td>
                <td>Queued</td>
                <td>2</td>
              </tr>
            </tbody>
          </AppTable>
        </section>
      </div>
    </AppCard>

    <section class="grid gap-4 xl:grid-cols-2">
      <AppCard class="space-y-4">
        <h2 class="text-lg font-semibold text-ink-primary">Buttons</h2>
        <div class="flex flex-wrap items-center gap-2">
          <AppButton>Primary</AppButton>
          <AppButton variant="secondary">Secondary</AppButton>
          <AppButton variant="ghost">Ghost</AppButton>
          <AppButton variant="danger">Danger</AppButton>
          <AppButton :disabled="true">Disabled</AppButton>
        </div>
        <p class="text-sm text-secondary">Use `primary` for main actions and `danger` for destructive actions.</p>
      </AppCard>

      <AppCard class="space-y-4">
        <h2 class="text-lg font-semibold text-ink-primary">Status System</h2>
        <div class="flex flex-wrap items-center gap-2">
          <AppBadge tone="neutral">Neutral</AppBadge>
          <AppBadge tone="info">Info</AppBadge>
          <AppBadge tone="success">Success</AppBadge>
          <AppBadge tone="warning">Warning</AppBadge>
          <AppBadge tone="danger">Danger</AppBadge>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <RunStatusBadge status="running" />
          <RunStatusBadge status="success" />
          <RunStatusBadge status="partial_failure" />
          <RunStatusBadge status="failed" />
        </div>
        <QueueHealthBadge :queued="2" :retrying="1" :dropped="1" />
      </AppCard>
    </section>

    <section class="grid gap-4 xl:grid-cols-2">
      <AppCard class="space-y-4">
        <h2 class="text-lg font-semibold text-ink-primary">Forms</h2>
        <form class="grid gap-3" @submit.prevent>
          <label class="grid gap-2 text-sm font-medium text-ink-secondary">
            <span>Name</span>
            <AppInput v-model="sampleName" autocomplete="name" />
          </label>

          <label class="grid gap-2 text-sm font-medium text-ink-secondary">
            <span>Email</span>
            <AppInput v-model="sampleEmail" type="email" autocomplete="email" />
          </label>

          <label class="grid gap-2 text-sm font-medium text-ink-secondary">
            <span>Role</span>
            <AppSelect v-model="sampleRole">
              <option value="viewer">Viewer</option>
              <option value="operator">Operator</option>
              <option value="admin">Admin</option>
            </AppSelect>
          </label>

          <AppCheckbox id="style-guide-enabled" v-model="sampleEnabled" label="Enabled" />

          <div class="flex flex-wrap items-center gap-2">
            <AppButton>Submit</AppButton>
            <AppButton variant="secondary" type="reset">Reset</AppButton>
          </div>
        </form>
      </AppCard>

      <AppCard class="space-y-4">
        <h2 class="text-lg font-semibold text-ink-primary">Alerts</h2>
        <AppAlert tone="info">
          <template #title>Informational</template>
          <p>Use for contextual guidance and non-critical notices.</p>
        </AppAlert>
        <AppAlert tone="success">
          <template #title>Success</template>
          <p>Use after completed mutations to confirm outcomes.</p>
        </AppAlert>
        <AppAlert tone="warning">
          <template #title>Warning</template>
          <p>Use when user intervention may be required soon.</p>
        </AppAlert>
      </AppCard>
    </section>

    <AppCard class="space-y-4">
      <h2 class="text-lg font-semibold text-ink-primary">Table Pattern</h2>
      <AppTable label="Style guide sample run table">
        <thead>
          <tr>
            <th scope="col">Run</th>
            <th scope="col">Title</th>
            <th scope="col">Owner</th>
            <th scope="col">Status</th>
            <th scope="col">Action</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in sampleRows" :key="row.id">
            <td>#{{ row.id }}</td>
            <td>{{ row.title }}</td>
            <td>{{ row.owner }}</td>
            <td><RunStatusBadge :status="row.status" /></td>
            <td><AppButton variant="ghost">Inspect</AppButton></td>
          </tr>
        </tbody>
      </AppTable>
    </AppCard>
  </AppPage>
</template>
