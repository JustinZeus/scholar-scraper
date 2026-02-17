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
  <div class="min-h-screen overflow-x-clip">
    <a href="#app-main" class="skip-link">Skip to main content</a>
    <RequestErrorPanel />

    <template v-if="showChrome">
      <AppHeader />
      <div
        class="grid min-h-[calc(100dvh-4.5rem)] grid-cols-1 lg:h-[calc(100dvh-4.5rem)] lg:min-h-[calc(100dvh-4.5rem)] lg:grid-cols-[17rem_minmax(0,1fr)]"
      >
        <AppNav class="lg:min-h-0 lg:overflow-y-auto" />
        <main id="app-main" class="min-w-0 px-4 py-6 sm:px-6 lg:min-h-0 lg:overflow-y-auto lg:px-8">
          <RouterView />
        </main>
      </div>
    </template>

    <main id="app-main" v-else class="min-h-screen overflow-x-clip">
      <RouterView />
    </main>
  </div>
</template>
