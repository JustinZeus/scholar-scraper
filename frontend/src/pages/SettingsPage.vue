<script setup lang="ts">
import { onMounted, ref } from "vue";

import AppPage from "@/components/layout/AppPage.vue";
import AppAlert from "@/components/ui/AppAlert.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppCheckbox from "@/components/ui/AppCheckbox.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppModal from "@/components/ui/AppModal.vue";
import AppSkeleton from "@/components/ui/AppSkeleton.vue";
import {
  changePassword,
  fetchSettings,
  updateSettings,
  type UserSettings,
} from "@/features/settings";
import { ApiRequestError } from "@/lib/api/errors";

const loading = ref(true);
const saving = ref(false);
const updatingPassword = ref(false);

const autoRunEnabled = ref(false);
const runIntervalMinutes = ref("60");
const requestDelaySeconds = ref("2");

const currentPassword = ref("");
const newPassword = ref("");
const confirmPassword = ref("");

const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);
const showIngestionModal = ref(false);
const showPasswordModal = ref(false);

function hydrateSettings(settings: UserSettings): void {
  autoRunEnabled.value = settings.auto_run_enabled;
  runIntervalMinutes.value = String(settings.run_interval_minutes);
  requestDelaySeconds.value = String(settings.request_delay_seconds);
}

function parsePositiveInteger(value: string, label: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${label} must be a positive integer.`);
  }
  return parsed;
}

async function loadSettings(): Promise<void> {
  loading.value = true;
  errorMessage.value = null;
  errorRequestId.value = null;

  try {
    const settings = await fetchSettings();
    hydrateSettings(settings);
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to load user settings.";
    }
  } finally {
    loading.value = false;
  }
}

async function onSaveSettings(): Promise<void> {
  saving.value = true;
  errorMessage.value = null;
  errorRequestId.value = null;
  successMessage.value = null;

  try {
    const payload: UserSettings = {
      auto_run_enabled: autoRunEnabled.value,
      run_interval_minutes: parsePositiveInteger(runIntervalMinutes.value, "Run interval"),
      request_delay_seconds: parsePositiveInteger(requestDelaySeconds.value, "Request delay"),
    };

    const saved = await updateSettings(payload);
    hydrateSettings(saved);
    successMessage.value = "Settings updated.";
    showIngestionModal.value = false;
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else if (error instanceof Error) {
      errorMessage.value = error.message;
    } else {
      errorMessage.value = "Unable to save settings.";
    }
  } finally {
    saving.value = false;
  }
}

async function onChangePassword(): Promise<void> {
  updatingPassword.value = true;
  errorMessage.value = null;
  errorRequestId.value = null;
  successMessage.value = null;

  try {
    if (!currentPassword.value || !newPassword.value || !confirmPassword.value) {
      throw new Error("All password fields are required.");
    }

    const response = await changePassword({
      current_password: currentPassword.value,
      new_password: newPassword.value,
      confirm_password: confirmPassword.value,
    });

    currentPassword.value = "";
    newPassword.value = "";
    confirmPassword.value = "";
    successMessage.value = response.message;
    showPasswordModal.value = false;
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else if (error instanceof Error) {
      errorMessage.value = error.message;
    } else {
      errorMessage.value = "Unable to change password.";
    }
  } finally {
    updatingPassword.value = false;
  }
}

onMounted(() => {
  void loadSettings();
});
</script>

<template>
  <AppPage title="Settings" subtitle="Configure ingestion and account controls.">
    <AppAlert v-if="successMessage" tone="success" dismissible @dismiss="successMessage = null">
      <template #title>Saved</template>
      <p>{{ successMessage }}</p>
    </AppAlert>

    <AppAlert v-if="errorMessage" tone="danger">
      <template #title>Settings request failed</template>
      <p>{{ errorMessage }}</p>
      <p class="text-secondary">Request ID: {{ errorRequestId || "n/a" }}</p>
    </AppAlert>

    <AppSkeleton v-if="loading" :lines="7" />

    <template v-else>
      <section class="grid gap-4 lg:grid-cols-2">
        <AppCard class="space-y-4">
          <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Scholar ingestion defaults</h2>
          <dl class="grid gap-2 text-sm text-secondary">
            <div class="flex items-center justify-between gap-2">
              <dt>Scheduler</dt>
              <dd class="font-semibold text-zinc-900 dark:text-zinc-100">
                {{ autoRunEnabled ? "Enabled" : "Disabled" }}
              </dd>
            </div>
            <div class="flex items-center justify-between gap-2">
              <dt>Run interval</dt>
              <dd class="font-semibold text-zinc-900 dark:text-zinc-100">{{ runIntervalMinutes }} min</dd>
            </div>
            <div class="flex items-center justify-between gap-2">
              <dt>Request delay</dt>
              <dd class="font-semibold text-zinc-900 dark:text-zinc-100">{{ requestDelaySeconds }} sec</dd>
            </div>
          </dl>
          <AppButton variant="secondary" @click="showIngestionModal = true">
            Manage ingestion settings
          </AppButton>
        </AppCard>

        <AppCard class="space-y-4">
          <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Account security</h2>
          <p class="text-sm text-secondary">Password changes are handled in a dedicated overlay to reduce clutter.</p>
          <AppButton variant="secondary" @click="showPasswordModal = true">Manage password</AppButton>
        </AppCard>
      </section>
    </template>

    <AppModal :open="showIngestionModal" title="Ingestion settings" @close="showIngestionModal = false">
      <form class="grid gap-3" @submit.prevent="onSaveSettings">
        <AppCheckbox id="auto-run-enabled" v-model="autoRunEnabled" label="Enable scheduler auto-run" />

        <label class="grid gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
          <span>Run interval (minutes)</span>
          <AppInput id="run-interval" v-model="runIntervalMinutes" type="number" min="1" />
        </label>

        <label class="grid gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
          <span>Request delay (seconds)</span>
          <AppInput id="request-delay" v-model="requestDelaySeconds" type="number" min="1" />
        </label>

        <div class="mt-2 flex flex-wrap justify-end gap-2">
          <AppButton
            variant="ghost"
            type="button"
            :disabled="saving"
            @click="showIngestionModal = false"
          >
            Cancel
          </AppButton>
          <AppButton type="submit" :disabled="saving">
            {{ saving ? "Saving..." : "Save settings" }}
          </AppButton>
        </div>
      </form>
    </AppModal>

    <AppModal :open="showPasswordModal" title="Change password" @close="showPasswordModal = false">
      <form class="grid gap-3" @submit.prevent="onChangePassword">
        <label class="grid gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
          <span>Current password</span>
          <AppInput v-model="currentPassword" type="password" autocomplete="current-password" />
        </label>

        <label class="grid gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
          <span>New password</span>
          <AppInput v-model="newPassword" type="password" autocomplete="new-password" />
        </label>

        <label class="grid gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
          <span>Confirm new password</span>
          <AppInput v-model="confirmPassword" type="password" autocomplete="new-password" />
        </label>

        <div class="mt-2 flex flex-wrap justify-end gap-2">
          <AppButton
            variant="ghost"
            type="button"
            :disabled="updatingPassword"
            @click="showPasswordModal = false"
          >
            Cancel
          </AppButton>
          <AppButton type="submit" :disabled="updatingPassword">
            {{ updatingPassword ? "Updating..." : "Change password" }}
          </AppButton>
        </div>
      </form>
    </AppModal>
  </AppPage>
</template>
