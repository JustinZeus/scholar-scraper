<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";

import RunStatusBadge from "@/components/patterns/RunStatusBadge.vue";
import ScrapeSafetyBadge from "@/components/patterns/ScrapeSafetyBadge.vue";
import AppButton from "@/components/ui/AppButton.vue";
import { formatCooldownCountdown } from "@/features/safety";
import { useAuthStore } from "@/stores/auth";
import { useRunStatusStore } from "@/stores/run_status";
import { useUserSettingsStore } from "@/stores/user_settings";

const auth = useAuthStore();
const runStatus = useRunStatusStore();
const userSettings = useUserSettingsStore();
const router = useRouter();
const emit = defineEmits<{
  (e: "navigate"): void;
}>();

const links = computed(() => {
  const base = [
    { id: "dashboard", to: "/dashboard", label: "Dashboard", adminOnly: false },
    { id: "scholars", to: "/scholars", label: "Scholars", adminOnly: false },
    { id: "publications", to: "/publications", label: "Publications", adminOnly: false },
    { id: "settings", to: "/settings", label: "Settings", adminOnly: false },
    { id: "style-guide", to: "/admin/style-guide", label: "Style Guide", adminOnly: true },
    { id: "runs", to: "/admin/runs", label: "Runs", adminOnly: true },
    { id: "users", to: "/admin/users", label: "Users", adminOnly: true },
  ];

  return base.filter((item) => {
    if (item.adminOnly && !auth.isAdmin) {
      return false;
    }
    return userSettings.isPageVisible(item.id);
  });
});
const navSafetyText = computed(() => {
  if (!userSettings.manualRunAllowed) {
    return "Manual checks disabled";
  }
  if (runStatus.safetyState.cooldown_active) {
    return `Cooldown: ${formatCooldownCountdown(runStatus.safetyState.cooldown_remaining_seconds)}`;
  }
  return "Safety ready";
});
const navRunStateStatus = computed(() => {
  if (runStatus.isSubmitting && !runStatus.isLikelyRunning) {
    return "starting";
  }
  if (runStatus.isLikelyRunning) {
    return "running";
  }
  return "idle";
});
const navRunStateLabel = computed(() =>
  navRunStateStatus.value
    .split("_")
    .filter((segment) => segment.length > 0)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" "),
);
const showSafetyRow = computed(
  () => runStatus.safetyState.cooldown_active || !userSettings.manualRunAllowed,
);

async function onLogout(): Promise<void> {
  emit("navigate");
  await auth.logout();
  await router.replace({ name: "login" });
}

function onNavigate(): void {
  emit("navigate");
}
</script>

<template>
  <aside
    class="min-h-0 min-w-0 overflow-x-hidden border-b border-stroke-subtle bg-surface-nav/70 px-4 py-4 lg:h-full lg:border-b-0 lg:border-r lg:px-5 lg:py-6"
  >
    <div class="flex h-full min-h-0 flex-col gap-4">
      <nav class="grid grid-cols-2 content-start gap-2 sm:grid-cols-3 lg:grid-cols-1" aria-label="Primary">
        <RouterLink
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          class="inline-flex min-h-10 min-w-0 items-center rounded-lg border border-transparent px-3 py-2 text-sm font-medium text-ink-secondary transition hover:border-stroke-interactive hover:bg-surface-card-muted hover:text-ink-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset"
          active-class="border-stroke-interactive bg-surface-nav-active font-semibold text-ink-primary shadow-sm hover:border-stroke-interactive hover:bg-surface-nav-active hover:text-ink-primary"
          @click="onNavigate"
        >
          {{ link.label }}
        </RouterLink>
      </nav>

      <div class="mt-auto grid gap-2 border-t border-stroke-subtle pt-3">
        <div class="grid gap-1 rounded-lg border border-stroke-default bg-surface-card-muted px-2.5 py-2 text-xs text-secondary">
          <div class="flex items-center justify-between gap-2">
            <span class="truncate">State: {{ navRunStateLabel }}</span>
            <RunStatusBadge :status="navRunStateStatus" />
          </div>
          <div
            v-if="showSafetyRow"
            class="flex items-center justify-between gap-2 border-t border-stroke-subtle pt-1"
          >
            <span class="truncate">{{ navSafetyText }}</span>
            <ScrapeSafetyBadge :state="runStatus.safetyState" />
          </div>
        </div>
        <AppButton variant="ghost" class="w-full justify-start" @click="onLogout">Logout</AppButton>
      </div>
    </div>
  </aside>
</template>
