<script setup lang="ts">
import { onMounted, ref } from "vue";

import AppPage from "@/components/layout/AppPage.vue";
import AppAlert from "@/components/ui/AppAlert.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppCheckbox from "@/components/ui/AppCheckbox.vue";
import AppEmptyState from "@/components/ui/AppEmptyState.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppSkeleton from "@/components/ui/AppSkeleton.vue";
import AppTable from "@/components/ui/AppTable.vue";
import {
  createAdminUser,
  listAdminUsers,
  setAdminUserActive,
  type AdminUser,
} from "@/features/admin_users";
import { ApiRequestError } from "@/lib/api/errors";

const loading = ref(true);
const creating = ref(false);
const togglingUserId = ref<number | null>(null);
const users = ref<AdminUser[]>([]);

const email = ref("");
const password = ref("");
const createIsAdmin = ref(false);

const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const successMessage = ref<string | null>(null);

function formatDate(value: string): string {
  const asDate = new Date(value);
  if (Number.isNaN(asDate.getTime())) {
    return value;
  }
  return asDate.toLocaleString();
}

async function loadUsers(): Promise<void> {
  loading.value = true;
  errorMessage.value = null;
  errorRequestId.value = null;

  try {
    users.value = await listAdminUsers();
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

onMounted(() => {
  void loadUsers();
});
</script>

<template>
  <AppPage title="Admin Users" subtitle="Create and manage user access for this instance.">
    <AppAlert v-if="successMessage" tone="success" dismissible @dismiss="successMessage = null">
      <template #title>Operation complete</template>
      <p>{{ successMessage }}</p>
    </AppAlert>

    <AppAlert v-if="errorMessage" tone="danger">
      <template #title>User management request failed</template>
      <p>{{ errorMessage }}</p>
      <p class="text-secondary">Request ID: {{ errorRequestId || "n/a" }}</p>
    </AppAlert>

    <section class="grid gap-4 lg:grid-cols-2">
      <AppCard class="space-y-4">
        <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Create User</h2>
        <form class="grid gap-3" @submit.prevent="onCreateUser">
          <label class="grid gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
            <span>Email</span>
            <AppInput id="admin-user-email" v-model="email" type="email" autocomplete="off" />
          </label>

          <label class="grid gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
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
        <h2 class="text-lg font-semibold text-zinc-900 dark:text-zinc-100">Users</h2>
        <AppSkeleton v-if="loading" :lines="5" />

        <AppEmptyState
          v-else-if="users.length === 0"
          title="No users available"
          body="Create an account to begin assigning access."
        />

        <AppTable v-else label="Admin users table">
          <thead>
            <tr>
              <th scope="col">Email</th>
              <th scope="col">Role</th>
              <th scope="col">Active</th>
              <th scope="col">Updated</th>
              <th scope="col">Action</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td>{{ user.email }}</td>
              <td>{{ user.is_admin ? "Admin" : "User" }}</td>
              <td>{{ user.is_active ? "Yes" : "No" }}</td>
              <td>{{ formatDate(user.updated_at) }}</td>
              <td>
                <AppButton
                  variant="secondary"
                  :disabled="togglingUserId === user.id"
                  @click="onToggleUser(user)"
                >
                  {{ user.is_active ? "Deactivate" : "Activate" }}
                </AppButton>
              </td>
            </tr>
          </tbody>
        </AppTable>
      </AppCard>
    </section>
  </AppPage>
</template>
