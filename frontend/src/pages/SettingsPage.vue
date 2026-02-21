<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import AppPage from "@/components/layout/AppPage.vue";
import AsyncStateGate from "@/components/patterns/AsyncStateGate.vue";
import RequestStateAlerts from "@/components/patterns/RequestStateAlerts.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppCheckbox from "@/components/ui/AppCheckbox.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppTabs, { type AppTabItem } from "@/components/ui/AppTabs.vue";
import SettingsAdminPanel from "@/features/settings/SettingsAdminPanel.vue";
import {
  changePassword,
  fetchSettings,
  type UserSettings,
  type UserSettingsUpdate,
  updateSettings,
} from "@/features/settings";
import { ApiRequestError } from "@/lib/api/errors";
import { useAuthStore } from "@/stores/auth";
import { useRunStatusStore } from "@/stores/run_status";
import { normalizeUserNavVisiblePages, useUserSettingsStore } from "@/stores/user_settings";

const TAB_CHECKING = "checking";
const TAB_ACCOUNT = "account";
const TAB_ADMIN_USERS = "admin-users";
const TAB_ADMIN_INTEGRITY = "admin-integrity";
const TAB_ADMIN_REPAIRS = "admin-repairs";
const TAB_ADMIN_PDF = "admin-pdf";

const auth = useAuthStore();
const userSettings = useUserSettingsStore();
const runStatus = useRunStatusStore();
const route = useRoute();
const router = useRouter();

const loading = ref(true);
const saving = ref(false);
const updatingPassword = ref(false);

const autoRunEnabled = ref(false);
const runIntervalMinutes = ref("60");
const requestDelaySeconds = ref("2");
const navVisiblePages = ref<string[]>([]);

const currentPassword = ref("");
const newPassword = ref("");
const confirmPassword = ref("");

const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);

const minCheckIntervalMinutes = ref(15);
const minRequestDelaySeconds = ref(2);
const automationAllowed = ref(true);
const manualRunAllowed = ref(true);

const activeTab = ref(TAB_CHECKING);

const tabItems = computed<AppTabItem[]>(() => {
  const tabs: AppTabItem[] = [
    { id: TAB_CHECKING, label: "Checking" },
    { id: TAB_ACCOUNT, label: "Account" },
  ];
  if (auth.isAdmin) {
    tabs.push(
      { id: TAB_ADMIN_USERS, label: "Users" },
      { id: TAB_ADMIN_INTEGRITY, label: "Integrity" },
      { id: TAB_ADMIN_REPAIRS, label: "Repairs" },
      { id: TAB_ADMIN_PDF, label: "PDF Queue" },
    );
  }
  return tabs;
});

const activeAdminSection = computed<"users" | "integrity" | "repairs" | "pdf" | null>(() => {
  if (activeTab.value === TAB_ADMIN_USERS) {
    return "users";
  }
  if (activeTab.value === TAB_ADMIN_INTEGRITY) {
    return "integrity";
  }
  if (activeTab.value === TAB_ADMIN_REPAIRS) {
    return "repairs";
  }
  if (activeTab.value === TAB_ADMIN_PDF) {
    return "pdf";
  }
  return null;
});

function isKnownTab(tabId: string): boolean {
  return tabItems.value.some((item) => item.id === tabId);
}

async function syncRouteTab(candidate: string): Promise<void> {
  const fallback = tabItems.value[0]?.id || TAB_CHECKING;
  const nextTab = isKnownTab(candidate) ? candidate : fallback;
  activeTab.value = nextTab;

  const currentQueryTab = typeof route.query.tab === "string" ? route.query.tab : "";
  if (currentQueryTab === nextTab) {
    return;
  }

  await router.replace({ query: { ...route.query, tab: nextTab } });
}

function hydrateSettings(settings: UserSettings): void {
  const parsedMinRunInterval = Number(settings.policy?.min_run_interval_minutes);
  minCheckIntervalMinutes.value = Number.isFinite(parsedMinRunInterval)
    ? Math.max(15, parsedMinRunInterval)
    : 15;

  const parsedMinRequestDelay = Number(settings.policy?.min_request_delay_seconds);
  minRequestDelaySeconds.value = Number.isFinite(parsedMinRequestDelay)
    ? Math.max(2, parsedMinRequestDelay)
    : 2;

  automationAllowed.value = Boolean(settings.policy?.automation_allowed ?? true);
  manualRunAllowed.value = Boolean(settings.policy?.manual_run_allowed ?? true);

  autoRunEnabled.value = Boolean(settings.auto_run_enabled) && automationAllowed.value;
  runIntervalMinutes.value = String(settings.run_interval_minutes);
  requestDelaySeconds.value = String(settings.request_delay_seconds);
  navVisiblePages.value = normalizeUserNavVisiblePages(settings.nav_visible_pages);

  userSettings.applySettings(settings);
  runStatus.setSafetyState(settings.safety_state);
}

function parseBoundedInteger(value: string, label: string, minimum: number): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed)) {
    throw new Error(`${label} must be a whole number.`);
  }
  if (parsed < minimum) {
    throw new Error(`${label} must be at least ${minimum}.`);
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
    const payload: UserSettingsUpdate = {
      auto_run_enabled: autoRunEnabled.value,
      run_interval_minutes: parseBoundedInteger(
        runIntervalMinutes.value,
        "Check interval (minutes)",
        minCheckIntervalMinutes.value,
      ),
      request_delay_seconds: parseBoundedInteger(
        requestDelaySeconds.value,
        "Delay between requests (seconds)",
        minRequestDelaySeconds.value,
      ),
      nav_visible_pages: normalizeUserNavVisiblePages(navVisiblePages.value),
    };

    const saved = await updateSettings(payload);
    hydrateSettings(saved);
    successMessage.value = "Settings updated.";
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

async function onSelectTab(tabId: string): Promise<void> {
  await syncRouteTab(tabId);
}

watch(
  () => route.query.tab,
  async (value) => {
    const requestedTab = typeof value === "string" ? value : TAB_CHECKING;
    await syncRouteTab(requestedTab);
  },
);

watch(
  () => auth.isAdmin,
  async () => {
    const requestedTab = typeof route.query.tab === "string" ? route.query.tab : TAB_CHECKING;
    await syncRouteTab(requestedTab);
  },
);

onMounted(async () => {
  await loadSettings();
  const requestedTab = typeof route.query.tab === "string" ? route.query.tab : TAB_CHECKING;
  await syncRouteTab(requestedTab);
});
</script>

<template>
  <AppPage title="Settings" subtitle="Configuration and account controls in one place.">
    <RequestStateAlerts
      :success-message="successMessage"
      success-title="Saved"
      :error-message="errorMessage"
      :error-request-id="errorRequestId"
      error-title="Settings request failed"
      @dismiss-success="successMessage = null"
    />

    <AsyncStateGate :loading="loading" :loading-lines="8" :show-empty="false">
      <AppCard class="grid gap-4">
        <AppTabs :model-value="activeTab" :items="tabItems" aria-label="Settings sections" @update:model-value="onSelectTab" />

        <section v-if="activeTab === TAB_CHECKING" class="grid gap-4">
          <div class="flex items-center gap-1">
            <h2 class="text-lg font-semibold text-ink-primary">Automatic Checking</h2>
            <AppHelpHint text="Controls when Scholarr runs automatic profile checks and how cautiously it scrapes." />
          </div>
          <p class="text-sm text-secondary">Configure background checks and request pacing for ingestion.</p>

          <div class="grid gap-3 md:grid-cols-2 md:items-start">
            <div class="grid gap-2 rounded-lg border border-stroke-default bg-surface-card-muted p-3 md:col-span-2">
              <AppCheckbox
                id="auto-run-enabled"
                v-model="autoRunEnabled"
                :disabled="!automationAllowed"
                label="Enable automatic background checks"
              />
              <p class="text-xs text-secondary">
                Automatic checks are {{ automationAllowed ? "enabled by policy." : "disabled by server safety policy." }}
              </p>
            </div>

            <label class="grid gap-2 text-sm font-medium text-ink-secondary">
              <span class="inline-flex items-center gap-1">
                Check interval (minutes)
                <AppHelpHint text="Minimum is controlled by server policy." />
              </span>
              <AppInput v-model="runIntervalMinutes" inputmode="numeric" />
              <span class="text-xs text-secondary">Minimum: {{ minCheckIntervalMinutes }}</span>
            </label>

            <label class="grid gap-2 text-sm font-medium text-ink-secondary">
              <span class="inline-flex items-center gap-1">
                Delay between requests (seconds)
                <AppHelpHint text="Minimum is controlled by safety policy to reduce blocks." />
              </span>
              <AppInput v-model="requestDelaySeconds" inputmode="numeric" />
              <span class="text-xs text-secondary">Minimum: {{ minRequestDelaySeconds }}</span>
            </label>
          </div>

          <div class="flex flex-wrap items-center gap-3 text-xs text-secondary">
            <span>Automation allowed: {{ automationAllowed ? "yes" : "no" }}</span>
            <span>Manual runs allowed: {{ manualRunAllowed ? "yes" : "no" }}</span>
          </div>

          <div>
            <AppButton :disabled="saving" @click="onSaveSettings">
              {{ saving ? "Saving..." : "Save checking settings" }}
            </AppButton>
          </div>
        </section>

        <section v-if="activeTab === TAB_ACCOUNT" class="grid gap-4">
          <div class="flex items-center gap-1">
            <h2 class="text-lg font-semibold text-ink-primary">Account Access</h2>
            <AppHelpHint text="Manage credentials for your current signed-in account on this instance." />
          </div>
          <p class="text-sm text-secondary">Change your sign-in password directly from this tab.</p>
          <form class="grid gap-3 rounded-lg border border-stroke-default bg-surface-card-muted p-3" @submit.prevent="onChangePassword">
            <label class="grid gap-1 text-sm font-medium text-ink-secondary">
              <span>Current password</span>
              <AppInput v-model="currentPassword" type="password" autocomplete="current-password" />
            </label>
            <label class="grid gap-1 text-sm font-medium text-ink-secondary">
              <span>New password</span>
              <AppInput v-model="newPassword" type="password" autocomplete="new-password" />
            </label>
            <label class="grid gap-1 text-sm font-medium text-ink-secondary">
              <span>Confirm new password</span>
              <AppInput v-model="confirmPassword" type="password" autocomplete="new-password" />
            </label>
            <div class="flex gap-2">
              <AppButton type="submit" :disabled="updatingPassword">
                {{ updatingPassword ? "Updating..." : "Update password" }}
              </AppButton>
            </div>
          </form>
        </section>

        <SettingsAdminPanel v-if="activeAdminSection" :section="activeAdminSection" />
      </AppCard>
    </AsyncStateGate>

  </AppPage>
</template>
