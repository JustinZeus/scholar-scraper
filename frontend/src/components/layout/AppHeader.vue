<script setup lang="ts">
import { computed } from "vue";

import AppButton from "@/components/ui/AppButton.vue";
import { useThemeStore } from "@/stores/theme";

const theme = useThemeStore();

const isDarkTheme = computed(() => theme.active === "dark");
const toggleThemeLabel = computed(() =>
  isDarkTheme.value ? "Switch to light theme" : "Switch to dark theme",
);

function onToggleTheme(): void {
  theme.setPreference(isDarkTheme.value ? "light" : "dark");
}
</script>

<template>
  <header class="sticky top-0 z-30 border-b border-zinc-200/70 bg-white/90 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/90">
    <div class="flex min-h-[4.5rem] w-full items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
      <div class="flex min-w-0 items-center gap-2">
        <RouterLink
          to="/dashboard"
          class="rounded-sm font-display text-lg tracking-tight text-zinc-900 transition hover:text-zinc-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-100 dark:text-zinc-100 dark:hover:text-zinc-300 dark:focus-visible:ring-brand-400 dark:focus-visible:ring-offset-zinc-950"
        >
          scholarr
        </RouterLink>
      </div>

      <div class="flex items-center justify-end">
        <AppButton
          variant="ghost"
          class="h-10 w-10 rounded-full p-0"
          :aria-label="toggleThemeLabel"
          :title="toggleThemeLabel"
          @click="onToggleTheme"
        >
          <span class="sr-only">{{ toggleThemeLabel }}</span>
          <svg
            v-if="isDarkTheme"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            class="h-5 w-5"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="4" />
            <path
              d="M12 2v2.5M12 19.5V22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M2 12h2.5M19.5 12H22M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"
            />
          </svg>
          <svg
            v-else
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            class="h-5 w-5"
            aria-hidden="true"
          >
            <path d="M21 14.5A8.5 8.5 0 1 1 9.5 3 7 7 0 0 0 21 14.5z" />
          </svg>
        </AppButton>
      </div>
    </div>
  </header>
</template>
