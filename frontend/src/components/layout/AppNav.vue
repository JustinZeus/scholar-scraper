<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";

import AppButton from "@/components/ui/AppButton.vue";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const router = useRouter();

const links = computed(() => {
  const base = [
    { to: "/dashboard", label: "Dashboard" },
    { to: "/scholars", label: "Scholars" },
    { to: "/publications", label: "Publications" },
    { to: "/settings", label: "Settings" },
  ];

  if (auth.isAdmin) {
    base.push({ to: "/admin/runs", label: "Runs" });
    base.push({ to: "/admin/users", label: "Users" });
  }

  return base;
});

async function onLogout(): Promise<void> {
  await auth.logout();
  await router.replace({ name: "login" });
}
</script>

<template>
  <aside
    class="min-w-0 border-b border-zinc-200 bg-white/70 px-4 py-4 dark:border-zinc-800 dark:bg-zinc-900/70 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:border-b-0 lg:border-r lg:px-5 lg:py-6"
  >
    <div class="flex h-full min-h-0 flex-col gap-4">
      <nav class="grid grid-cols-2 content-start gap-2 sm:grid-cols-3 lg:grid-cols-1" aria-label="Primary">
        <RouterLink
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          class="inline-flex min-h-10 min-w-0 items-center rounded-lg border border-transparent px-3 py-2 text-sm font-medium text-zinc-600 transition hover:border-zinc-300 hover:bg-zinc-50 hover:text-zinc-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-100 dark:text-zinc-300 dark:hover:border-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-100 dark:focus-visible:ring-brand-400 dark:focus-visible:ring-offset-zinc-950"
          active-class="border-zinc-900 bg-zinc-900 text-white hover:border-zinc-900 hover:bg-zinc-900 hover:text-white dark:border-brand-400 dark:bg-brand-400 dark:text-zinc-950 dark:hover:border-brand-300 dark:hover:bg-brand-300"
        >
          {{ link.label }}
        </RouterLink>
      </nav>

      <div class="mt-auto grid gap-2 border-t border-zinc-200 pt-3 dark:border-zinc-800">
        <p class="truncate text-xs text-zinc-500 dark:text-zinc-400">{{ auth.user?.email }}</p>
        <AppButton variant="ghost" class="w-full justify-start" @click="onLogout">Logout</AppButton>
      </div>
    </div>
  </aside>
</template>
