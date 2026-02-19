<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import AppPage from "@/components/layout/AppPage.vue";
import AsyncStateGate from "@/components/patterns/AsyncStateGate.vue";
import RequestStateAlerts from "@/components/patterns/RequestStateAlerts.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppCheckbox from "@/components/ui/AppCheckbox.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppModal from "@/components/ui/AppModal.vue";
import {
  changePassword,
  fetchSettings,
  type UserSettings,
  updateSettings,
} from "@/features/settings";
import { ApiRequestError } from "@/lib/api/errors";
import { useAuthStore } from "@/stores/auth";
import { normalizeUserNavVisiblePages, useUserSettingsStore } from "@/stores/user_settings";

interface NavPageOption {
  id: string;
  label: string;
  description: string;
  required: boolean;
  adminOnly?: boolean;
}

const NAV_PAGE_OPTIONS: NavPageOption[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    description: "Overview and latest publication updates.",
    required: true,
  },
  {
    id: "scholars",
    label: "Scholars",
    description: "Tracked scholar profiles and profile management.",
    required: true,
  },
  {
    id: "publications",
    label: "Publications",
    description: "Review and search discovered publication records.",
    required: false,
  },
  {
    id: "settings",
    label: "Settings",
    description: "Configuration and account controls.",
    required: true,
  },
  {
    id: "style-guide",
    label: "Style Guide",
    description: "Admin-only visual reference for theme and component tokens.",
    required: false,
    adminOnly: true,
  },
  {
    id: "runs",
    label: "Runs",
    description: "Admin-only diagnostics and queue operations.",
    required: false,
    adminOnly: true,
  },
  {
    id: "users",
    label: "Users",
    description: "Admin-only user management.",
    required: false,
    adminOnly: true,
  },
];

const auth = useAuthStore();
const userSettings = useUserSettingsStore();

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
const showIngestionModal = ref(false);
const showPasswordModal = ref(false);
const showNavigationModal = ref(false);
const MIN_CHECK_INTERVAL_MINUTES = 15;
const MIN_REQUEST_DELAY_SECONDS = 2;

const visibleNavOptions = computed(() =>
  NAV_PAGE_OPTIONS.filter((option) => !option.adminOnly || auth.isAdmin),
);
const visibleNavLabels = computed(() =>
  visibleNavOptions.value
    .filter((option) => navVisiblePages.value.includes(option.id))
    .map((option) => option.label),
);

function hydrateSettings(settings: UserSettings): void {
  autoRunEnabled.value = settings.auto_run_enabled;
  runIntervalMinutes.value = String(settings.run_interval_minutes);
  requestDelaySeconds.value = String(settings.request_delay_seconds);
  navVisiblePages.value = normalizeUserNavVisiblePages(settings.nav_visible_pages);
  userSettings.applySettings(settings);
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

function isNavPageVisible(pageId: string): boolean {
  return navVisiblePages.value.includes(pageId);
}

function onToggleNavPage(page: NavPageOption, event: Event): void {
  const input = event.target as HTMLInputElement;
  if (page.required && !input.checked) {
    return;
  }

  if (input.checked) {
    navVisiblePages.value = normalizeUserNavVisiblePages([...navVisiblePages.value, page.id]);
    return;
  }

  navVisiblePages.value = normalizeUserNavVisiblePages(
    navVisiblePages.value.filter((pageId) => pageId !== page.id),
  );
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
      run_interval_minutes: parseBoundedInteger(
        runIntervalMinutes.value,
        "Check interval (minutes)",
        MIN_CHECK_INTERVAL_MINUTES,
      ),
      request_delay_seconds: parseBoundedInteger(
        requestDelaySeconds.value,
        "Delay between requests (seconds)",
        MIN_REQUEST_DELAY_SECONDS,
      ),
      nav_visible_pages: normalizeUserNavVisiblePages(navVisiblePages.value),
    };

    const saved = await updateSettings(payload);
    hydrateSettings(saved);
    successMessage.value = "Settings updated.";
    showIngestionModal.value = false;
    showNavigationModal.value = false;
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
  <AppPage
    title="Settings"
    subtitle="Control how often Scholarr checks profiles and how cautiously it sends requests."
  >
    <RequestStateAlerts
      :success-message="successMessage"
      success-title="Saved"
      :error-message="errorMessage"
      :error-request-id="errorRequestId"
      error-title="Settings request failed"
      @dismiss-success="successMessage = null"
    />

    <AsyncStateGate :loading="loading" :loading-lines="7" :show-empty="false">
      <section class="grid gap-4 xl:grid-cols-3">
        <AppCard class="flex h-full flex-col gap-4">
          <div class="flex items-center gap-1">
            <h2 class="text-lg font-semibold text-ink-primary">Automatic Checking</h2>
            <AppHelpHint text="Controls when Scholarr runs automatic profile checks and how cautiously it scrapes." />
          </div>
          <p class="text-sm text-secondary">
            Configure the background checker that looks for new publications on your tracked profiles.
          </p>
          <dl class="grid gap-2 text-sm text-secondary">
            <div class="flex items-center justify-between gap-2">
              <dt>Automatic checks</dt>
              <dd class="font-semibold text-ink-primary">
                {{ autoRunEnabled ? "Enabled" : "Disabled" }}
              </dd>
            </div>
            <div class="flex items-center justify-between gap-2">
              <dt>Check interval</dt>
              <dd class="font-semibold text-ink-primary">Every {{ runIntervalMinutes }} min</dd>
            </div>
            <div class="flex items-center justify-between gap-2">
              <dt>Delay between requests</dt>
              <dd class="font-semibold text-ink-primary">{{ requestDelaySeconds }} sec</dd>
            </div>
          </dl>
          <AppButton variant="secondary" class="mt-auto self-start" @click="showIngestionModal = true">
            Edit checking rules
          </AppButton>
        </AppCard>

        <AppCard class="flex h-full flex-col gap-4">
          <div class="flex items-center gap-1">
            <h2 class="text-lg font-semibold text-ink-primary">Account Access</h2>
            <AppHelpHint text="Manage credentials for your current signed-in account on this instance." />
          </div>
          <p class="text-sm text-secondary">
            Change your sign-in password from a focused view. This does not affect other users.
          </p>
          <AppButton variant="secondary" class="mt-auto self-start" @click="showPasswordModal = true">
            Change password
          </AppButton>
        </AppCard>

        <AppCard class="flex h-full flex-col gap-4">
          <div class="flex items-center gap-1">
            <h2 class="text-lg font-semibold text-ink-primary">Navigation</h2>
            <AppHelpHint text="Choose which pages appear in the left sidebar. Dashboard, Scholars, and Settings are always visible." />
          </div>
          <p class="text-sm text-secondary">
            Visible now: {{ visibleNavLabels.length > 0 ? visibleNavLabels.join(", ") : "none" }}.
          </p>
          <AppButton variant="secondary" class="mt-auto self-start" @click="showNavigationModal = true">
            Customize sidebar pages
          </AppButton>
        </AppCard>
      </section>
    </AsyncStateGate>

    <AppModal
      :open="showIngestionModal"
      title="Automatic Checking Settings"
      @close="showIngestionModal = false"
    >
      <form class="grid gap-3" @submit.prevent="onSaveSettings">
        <AppCheckbox id="auto-run-enabled" v-model="autoRunEnabled" label="Enable automatic background checks" />

        <label class="grid gap-2 text-sm font-medium text-ink-secondary">
          <span class="inline-flex items-center gap-1">
            Check interval (minutes)
            <AppHelpHint text="How often Scholarr starts a background update check." />
          </span>
          <AppInput id="run-interval" v-model="runIntervalMinutes" type="number" :min="MIN_CHECK_INTERVAL_MINUTES" />
          <span class="text-xs text-secondary">Minimum: {{ MIN_CHECK_INTERVAL_MINUTES }} minutes.</span>
        </label>

        <label class="grid gap-2 text-sm font-medium text-ink-secondary">
          <span class="inline-flex items-center gap-1">
            Delay between requests (seconds)
            <AppHelpHint text="Pause between profile requests during a check. Higher values are slower but safer." />
          </span>
          <AppInput
            id="request-delay"
            v-model="requestDelaySeconds"
            type="number"
            :min="MIN_REQUEST_DELAY_SECONDS"
          />
          <span class="text-xs text-secondary">Minimum: {{ MIN_REQUEST_DELAY_SECONDS }} seconds.</span>
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

    <AppModal :open="showPasswordModal" title="Change Sign-in Password" @close="showPasswordModal = false">
      <form class="grid gap-3" @submit.prevent="onChangePassword">
        <label class="grid gap-2 text-sm font-medium text-ink-secondary">
          <span>Current password</span>
          <AppInput v-model="currentPassword" type="password" autocomplete="current-password" />
        </label>

        <label class="grid gap-2 text-sm font-medium text-ink-secondary">
          <span>New password</span>
          <AppInput v-model="newPassword" type="password" autocomplete="new-password" />
        </label>

        <label class="grid gap-2 text-sm font-medium text-ink-secondary">
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

    <AppModal :open="showNavigationModal" title="Sidebar Page Visibility" @close="showNavigationModal = false">
      <form class="grid gap-3" @submit.prevent="onSaveSettings">
        <p class="text-sm text-secondary">
          Turn optional pages on or off in the sidebar for your account.
        </p>

        <ul class="grid gap-2">
          <li
            v-for="option in visibleNavOptions"
            :key="option.id"
            class="rounded-lg border border-stroke-default bg-surface-card-muted/70 px-3 py-2"
          >
            <label class="flex items-start gap-3">
              <input
                type="checkbox"
                class="mt-0.5 h-4 w-4 rounded border-stroke-interactive bg-surface-input text-brand-600 focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset"
                :checked="isNavPageVisible(option.id)"
                :disabled="saving || option.required"
                @change="onToggleNavPage(option, $event)"
              />
              <span class="grid gap-0.5">
                <span class="text-sm font-medium text-ink-primary">
                  {{ option.label }}
                  <span v-if="option.required" class="ml-1 text-xs text-ink-muted">(required)</span>
                </span>
                <span class="text-xs text-secondary">{{ option.description }}</span>
              </span>
            </label>
          </li>
        </ul>

        <div class="mt-2 flex flex-wrap justify-end gap-2">
          <AppButton
            variant="ghost"
            type="button"
            :disabled="saving"
            @click="showNavigationModal = false"
          >
            Cancel
          </AppButton>
          <AppButton type="submit" :disabled="saving">
            {{ saving ? "Saving..." : "Save sidebar settings" }}
          </AppButton>
        </div>
      </form>
    </AppModal>
  </AppPage>
</template>
