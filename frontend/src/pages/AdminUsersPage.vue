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
import AppTable from "@/components/ui/AppTable.vue";
import {
  createAdminUser,
  listAdminUsers,
  resetAdminUserPassword,
  setAdminUserActive,
  type AdminUser,
} from "@/features/admin_users";
import { ApiRequestError } from "@/lib/api/errors";

const loading = ref(true);
const creating = ref(false);
const togglingUserId = ref<number | null>(null);
const resettingPassword = ref(false);
const activeUserId = ref<number | null>(null);
const users = ref<AdminUser[]>([]);

const email = ref("");
const password = ref("");
const createIsAdmin = ref(false);
const resetPassword = ref("");

const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);

const activeUser = computed(() => users.value.find((item) => item.id === activeUserId.value) ?? null);

function formatDate(value: string): string {
  const asDate = new Date(value);
  if (Number.isNaN(asDate.getTime())) {
    return value;
  }
  return asDate.toLocaleString();
}

function userRoleLabel(user: AdminUser): string {
  return user.is_admin ? "Admin" : "User";
}

function statusDotClass(user: AdminUser): string {
  return user.is_active
    ? "bg-success-500 ring-success-200"
    : "bg-ink-muted/70 ring-stroke-default";
}

function openUserModal(user: AdminUser): void {
  activeUserId.value = user.id;
  resetPassword.value = "";
}

function closeUserModal(): void {
  activeUserId.value = null;
  resetPassword.value = "";
}

async function loadUsers(): Promise<void> {
  loading.value = true;
  errorMessage.value = null;
  errorRequestId.value = null;

  try {
    users.value = await listAdminUsers();
    if (activeUserId.value !== null && !users.value.some((item) => item.id === activeUserId.value)) {
      closeUserModal();
    }
  } catch (error) {
    users.value = [];
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to load users.";
    }
  } finally {
    loading.value = false;
  }
}

async function onCreateUser(): Promise<void> {
  creating.value = true;
  successMessage.value = null;
  errorMessage.value = null;
  errorRequestId.value = null;

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
    await loadUsers();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else if (error instanceof Error) {
      errorMessage.value = error.message;
    } else {
      errorMessage.value = "Unable to create user.";
    }
  } finally {
    creating.value = false;
  }
}

async function onToggleUser(user: AdminUser): Promise<void> {
  togglingUserId.value = user.id;
  successMessage.value = null;

  try {
    const updated = await setAdminUserActive(user.id, !user.is_active);
    successMessage.value = `${updated.email} is now ${updated.is_active ? "active" : "inactive"}.`;
    await loadUsers();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else {
      errorMessage.value = "Unable to update user.";
    }
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
  successMessage.value = null;
  errorMessage.value = null;
  errorRequestId.value = null;

  try {
    const candidate = resetPassword.value.trim();
    if (candidate.length < 12) {
      throw new Error("New password must be at least 12 characters.");
    }

    const result = await resetAdminUserPassword(user.id, candidate);
    successMessage.value = result.message || `Password reset for ${user.email}.`;
    resetPassword.value = "";
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
    } else if (error instanceof Error) {
      errorMessage.value = error.message;
    } else {
      errorMessage.value = "Unable to reset password.";
    }
  } finally {
    resettingPassword.value = false;
  }
}

onMounted(() => {
  void loadUsers();
});
</script>

<template>
  <AppPage title="Admin Users" subtitle="Create and manage user access for this instance.">
    <RequestStateAlerts
      :success-message="successMessage"
      :error-message="errorMessage"
      :error-request-id="errorRequestId"
      error-title="User management request failed"
      @dismiss-success="successMessage = null"
    />

    <section class="grid gap-4 lg:grid-cols-2">
      <AppCard class="space-y-4">
        <div class="flex items-center gap-1">
          <h2 class="text-lg font-semibold text-ink-primary">Create User</h2>
          <AppHelpHint text="Create local accounts for this Scholarr instance and optionally grant admin rights." />
        </div>
        <form class="grid gap-3" @submit.prevent="onCreateUser">
          <label class="grid gap-2 text-sm font-medium text-ink-secondary">
            <span>Email</span>
            <AppInput id="admin-user-email" v-model="email" type="email" autocomplete="off" />
          </label>

          <label class="grid gap-2 text-sm font-medium text-ink-secondary">
            <span>Password</span>
            <AppInput id="admin-user-password" v-model="password" type="password" autocomplete="new-password" />
          </label>

          <AppCheckbox id="admin-user-is-admin" v-model="createIsAdmin" label="Grant admin privileges" />

          <AppButton type="submit" :disabled="creating">
            {{ creating ? "Creating..." : "Create user" }}
          </AppButton>
        </form>
      </AppCard>

      <AppCard class="space-y-4">
        <div class="flex items-center gap-1">
          <h2 class="text-lg font-semibold text-ink-primary">Users</h2>
          <AppHelpHint text="Review account roles and active status. Inactive users cannot sign in." />
        </div>
        <AsyncStateGate
          :loading="loading"
          :loading-lines="5"
          :empty="users.length === 0"
          :show-empty="!errorMessage"
          empty-title="No users available"
          empty-body="Create an account to begin assigning access."
        >
          <AppTable label="Admin users table">
            <thead>
              <tr>
                <th scope="col">Email</th>
                <th scope="col">Role</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="user in users" :key="user.id">
                <td>
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
              </tr>
            </tbody>
          </AppTable>
          <p class="text-xs text-secondary">Status dot: green is active, gray is inactive. Click an email to manage.</p>
        </AsyncStateGate>
      </AppCard>
    </section>

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
          <p class="text-xs text-secondary">Last updated: {{ formatDate(activeUser.updated_at) }}</p>
        </div>

        <div class="grid gap-2 border-t border-stroke-default pt-3">
          <label class="grid gap-2 text-sm font-medium text-ink-secondary" for="admin-user-reset-password">
            <span>Reset password</span>
            <AppInput
              id="admin-user-reset-password"
              v-model="resetPassword"
              type="password"
              autocomplete="new-password"
              placeholder="Minimum 12 characters"
              :disabled="resettingPassword"
            />
          </label>
          <div class="flex flex-wrap justify-end gap-2">
            <AppButton variant="secondary" :disabled="resettingPassword" @click="onResetPassword">
              {{ resettingPassword ? "Resetting..." : "Reset password" }}
            </AppButton>
          </div>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-2 border-t border-stroke-default pt-3">
          <AppButton
            variant="secondary"
            :disabled="togglingUserId === activeUser.id"
            @click="onToggleUser(activeUser)"
          >
            {{ activeUser.is_active ? "Deactivate user" : "Activate user" }}
          </AppButton>
          <AppButton variant="ghost" :disabled="togglingUserId === activeUser.id || resettingPassword" @click="closeUserModal">
            Close
          </AppButton>
        </div>
      </div>
    </AppModal>
  </AppPage>
</template>
