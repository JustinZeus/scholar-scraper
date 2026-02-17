<script setup lang="ts">
import { ref } from "vue";

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

const sampleName = ref("Ada Lovelace");
const sampleEmail = ref("ada@example.com");
const sampleRole = ref("operator");
const sampleEnabled = ref(true);

const sampleRows = [
  { id: 101, title: "Entity Resolution Improvements", status: "running", owner: "Scheduler" },
  { id: 102, title: "Retry Queue Drain", status: "partial_failure", owner: "Ops" },
  { id: 103, title: "Weekly Publication Sync", status: "success", owner: "Ingestion" },
];
</script>

<template>
  <AppPage
    title="Style Guide"
    subtitle="Reference page for Tailwind component patterns used across the application."
  >
    <section class="grid gap-4 xl:grid-cols-2">
      <AppCard class="space-y-4">
        <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Buttons</h2>
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
        <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Status System</h2>
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
        <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Forms</h2>
        <form class="grid gap-3" @submit.prevent>
          <label class="grid gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
            <span>Name</span>
            <AppInput v-model="sampleName" autocomplete="name" />
          </label>

          <label class="grid gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
            <span>Email</span>
            <AppInput v-model="sampleEmail" type="email" autocomplete="email" />
          </label>

          <label class="grid gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
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
        <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Alerts</h2>
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
      <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Table Pattern</h2>
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
