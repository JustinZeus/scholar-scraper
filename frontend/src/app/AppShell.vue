<script setup lang="ts">
import { computed } from "vue";
import { RouterView } from "vue-router";

import AppHeader from "@/components/layout/AppHeader.vue";
import AppNav from "@/components/layout/AppNav.vue";
import RequestErrorPanel from "@/components/patterns/RequestErrorPanel.vue";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const showChrome = computed(() => auth.isAuthenticated);
</script>

<template>
  <div class="h-[100dvh] max-h-[100dvh] w-full max-w-full overflow-hidden">
    <a href="#app-main" class="skip-link">Skip to main content</a>
    <RequestErrorPanel />

    <template v-if="showChrome">
      <AppHeader />
      <div
        class="grid h-[calc(100dvh-4.5rem)] min-h-0 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] lg:grid-cols-[17rem_minmax(0,1fr)] lg:grid-rows-1"
      >
        <AppNav class="min-h-0 overflow-x-hidden lg:overflow-y-auto" />
        <main id="app-main" class="min-h-0 min-w-0 overflow-y-auto overflow-x-hidden px-4 py-6 sm:px-6 lg:px-8">
          <RouterView />
        </main>
      </div>
    </template>

    <main
      id="app-main"
      v-else
      class="h-[100dvh] max-h-[100dvh] min-h-0 min-w-0 overflow-y-auto overflow-x-hidden"
    >
      <RouterView />
    </main>
  </div>
</template>
