<script setup lang="ts">
import { computed, ref } from "vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppCheckbox from "@/components/ui/AppCheckbox.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppModal from "@/components/ui/AppModal.vue";
import AppRefreshButton from "@/components/ui/AppRefreshButton.vue";
import AppTable from "@/components/ui/AppTable.vue";
import {
  createAdminUser,
  listAdminUsers,
  resetAdminUserPassword,
  setAdminUserActive,
  type AdminUser,
} from "@/features/admin_users";
import { useRequestState } from "@/composables/useRequestState";

const { errorMessage, errorRequestId, successMessage, clearAlerts, assignError, setSuccess } = useRequestState();

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

const activeUser = computed(() => users.value.find((u) => u.id === activeUserId.value) ?? null);

function userRoleLabel(user: AdminUser): string {
  return user.is_admin ? "Admin" : "User";
}

function statusDotClass(user: AdminUser): string {
  return user.is_active ? "bg-success-500 ring-success-200" : "bg-ink-muted/70 ring-stroke-default";
}

function formatTimestamp(value: string | null): string {
  if (!value) return "n/a";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function openUserModal(user: AdminUser): void {
  activeUserId.value = user.id;
  resetPassword.value = "";
}

function closeUserModal(): void {
  activeUserId.value = null;
  resetPassword.value = "";
}

async function refreshUsers(): Promise<void> {
  refreshingUsers.value = true;
  try {
    users.value = await listAdminUsers();
    if (activeUserId.value !== null && !users.value.some((item) => item.id === activeUserId.value)) {
      closeUserModal();
    }
  } finally {
    refreshingUsers.value = false;
  }
}

async function onCreateUser(): Promise<void> {
  creating.value = true;
  clearAlerts();
  try {
    if (!email.value.trim() || !password.value) throw new Error("Email and password are required.");
    const created = await createAdminUser({ email: email.value.trim(), password: password.value, is_admin: createIsAdmin.value });
    email.value = "";
    password.value = "";
    createIsAdmin.value = false;
    setSuccess(`User created: ${created.email}`);
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
    setSuccess(`${updated.email} is now ${updated.is_active ? "active" : "inactive"}.`);
    await refreshUsers();
  } catch (error) {
    assignError(error, "Unable to update user.");
  } finally {
    togglingUserId.value = null;
  }
}

async function onResetPassword(): Promise<void> {
  const user = activeUser.value;
  if (!user) return;
  resettingPassword.value = true;
  clearAlerts();
  try {
    const candidate = resetPassword.value.trim();
    if (candidate.length < 12) throw new Error("New password must be at least 12 characters.");
    const result = await resetAdminUserPassword(user.id, candidate);
    resetPassword.value = "";
    setSuccess(result.message || `Password reset for ${user.email}.`);
  } catch (error) {
    assignError(error, "Unable to reset password.");
  } finally {
    resettingPassword.value = false;
  }
}

async function load(): Promise<void> {
  await refreshUsers();
}

defineExpose({ load, errorMessage, errorRequestId, successMessage, users });
</script>

<template>
  <AppCard class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-1">
        <h2 class="text-lg font-semibold text-ink-primary">Users</h2>
        <AppHelpHint text="Create accounts, toggle active status, and reset passwords." />
      </div>
      <AppRefreshButton variant="secondary" :loading="refreshingUsers" title="Refresh users" loading-title="Refreshing users" @click="refreshUsers" />
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
          <AppButton type="submit" :disabled="creating">{{ creating ? "Creating..." : "Create user" }}</AppButton>
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
            <button type="button" class="group inline-flex items-center gap-2 rounded-md px-1 py-0.5 text-left text-ink-primary transition hover:bg-surface-card-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset" @click="openUserModal(user)">
              <span :class="statusDotClass(user)" class="h-2.5 w-2.5 rounded-full ring-2" :aria-label="user.is_active ? 'Active user' : 'Inactive user'" />
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

  <AppModal :open="activeUser !== null" title="User settings" @close="closeUserModal">
    <div v-if="activeUser" class="grid gap-4">
      <div class="space-y-1">
        <div class="flex items-center gap-2">
          <span :class="statusDotClass(activeUser)" class="h-2.5 w-2.5 rounded-full ring-2" :aria-label="activeUser.is_active ? 'Active user' : 'Inactive user'" />
          <p class="truncate text-sm font-semibold text-ink-primary">{{ activeUser.email }}</p>
        </div>
        <p class="text-sm text-secondary">Role: {{ userRoleLabel(activeUser) }}</p>
        <p class="text-xs text-secondary">Last updated: {{ formatTimestamp(activeUser.updated_at) }}</p>
      </div>
      <div class="grid gap-2">
        <label class="grid gap-1 text-sm font-medium text-ink-secondary">
          <span>New password</span>
          <AppInput id="admin-reset-password" v-model="resetPassword" type="password" autocomplete="new-password" placeholder="At least 12 characters" />
        </label>
        <div class="flex flex-wrap gap-2">
          <AppButton :disabled="resettingPassword" @click="onResetPassword">{{ resettingPassword ? "Resetting..." : "Reset password" }}</AppButton>
          <AppButton variant="secondary" :disabled="togglingUserId === activeUser.id" @click="onToggleUser(activeUser)">
            {{ togglingUserId === activeUser.id ? "Updating..." : activeUser.is_active ? "Deactivate user" : "Activate user" }}
          </AppButton>
        </div>
      </div>
    </div>
  </AppModal>
</template>
