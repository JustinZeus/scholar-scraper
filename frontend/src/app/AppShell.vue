<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { RouterView, useRoute } from "vue-router";

import AppHeader from "@/components/layout/AppHeader.vue";
import AppNav from "@/components/layout/AppNav.vue";
import RequestErrorPanel from "@/components/patterns/RequestErrorPanel.vue";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const showChrome = computed(() => auth.isAuthenticated);
const shouldLockMainScroll = computed(() => route.meta.lockMainScroll === true);
const isMobileNavOpen = ref(false);

function closeMobileNav(): void {
  isMobileNavOpen.value = false;
}

function toggleMobileNav(): void {
  isMobileNavOpen.value = !isMobileNavOpen.value;
}

watch(
  () => route.fullPath,
  () => {
    closeMobileNav();
  },
);

watch(showChrome, (value) => {
  if (!value) {
    closeMobileNav();
  }
});
</script>

<template>
  <div class="min-h-[100dvh] w-full max-w-full overflow-visible lg:h-[100dvh] lg:max-h-[100dvh] lg:overflow-hidden">
    <a href="#app-main" class="skip-link">Skip to main content</a>
    <RequestErrorPanel />

    <template v-if="showChrome">
      <AppHeader
        :show-menu-button="true"
        :menu-open="isMobileNavOpen"
        @toggle-menu="toggleMobileNav"
      />
      <div class="relative min-h-0 lg:grid lg:h-[calc(100dvh-4.5rem)] lg:grid-cols-[17rem_minmax(0,1fr)] lg:grid-rows-1">
        <button
          v-if="isMobileNavOpen"
          type="button"
          class="absolute inset-0 z-30 bg-surface-overlay/35 backdrop-blur-[1px] lg:hidden"
          aria-label="Close navigation menu"
          @click="closeMobileNav"
        />
        <div
          id="mobile-primary-nav"
          class="absolute inset-y-0 left-0 z-40 w-[17rem] max-w-[85vw] min-h-0 bg-surface-nav shadow-xl transition-transform duration-200 ease-out lg:static lg:z-auto lg:w-auto lg:max-w-none lg:bg-transparent lg:shadow-none lg:transition-none"
          :class="isMobileNavOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'"
        >
          <AppNav
            class="h-full min-h-0 overflow-x-hidden overflow-y-auto lg:h-auto lg:overflow-y-auto"
            @navigate="closeMobileNav"
          />
        </div>
        <main
          id="app-main"
          class="min-h-0 min-w-0 overflow-x-hidden overflow-y-visible px-4 py-6 sm:px-6 lg:col-start-2 lg:overflow-y-auto lg:px-8"
          :class="shouldLockMainScroll ? 'lg:overflow-y-hidden' : ''"
        >
          <RouterView />
        </main>
      </div>
    </template>

    <main
      id="app-main"
      v-else
      class="min-h-[100dvh] min-w-0 overflow-x-hidden overflow-y-visible lg:h-[100dvh] lg:max-h-[100dvh] lg:overflow-y-auto"
    >
      <RouterView />
    </main>
  </div>
</template>
