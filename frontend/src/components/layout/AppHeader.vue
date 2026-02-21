<script setup lang="ts">
import { computed } from "vue";

import AppButton from "@/components/ui/AppButton.vue";
import AppBrandMark from "@/components/ui/AppBrandMark.vue";
import AppThemePicker from "@/components/ui/AppThemePicker.vue";

const props = withDefaults(
  defineProps<{
    showMenuButton?: boolean;
    menuOpen?: boolean;
  }>(),
  {
    showMenuButton: false,
    menuOpen: false,
  },
);
const emit = defineEmits<{
  (e: "toggle-menu"): void;
}>();

const menuButtonLabel = computed(() =>
  props.menuOpen ? "Close navigation menu" : "Open navigation menu",
);

function onToggleMenu(): void {
  emit("toggle-menu");
}
</script>

<template>
  <header class="sticky top-0 z-30 border-b border-stroke-subtle bg-surface-nav/90 backdrop-blur">
    <div class="flex min-h-[4.5rem] w-full items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
      <div class="flex min-w-0 items-center gap-2">
        <AppButton
          v-if="props.showMenuButton"
          variant="ghost"
          class="h-10 w-10 rounded-full p-0 lg:hidden"
          :aria-label="menuButtonLabel"
          :aria-expanded="props.menuOpen"
          aria-controls="mobile-primary-nav"
          :title="menuButtonLabel"
          @click="onToggleMenu"
        >
          <span class="sr-only">{{ menuButtonLabel }}</span>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            class="h-5 w-5"
            aria-hidden="true"
          >
            <path v-if="props.menuOpen" d="M6 6l12 12M18 6 6 18" />
            <path v-else d="M4 7h16M4 12h16M4 17h16" />
          </svg>
        </AppButton>
        <RouterLink
          to="/dashboard"
          class="inline-flex items-center gap-2.5 rounded-sm font-display text-xl tracking-tight text-ink-primary transition hover:text-ink-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset"
        >
          <AppBrandMark size="xl" />
          <span>scholarr</span>
        </RouterLink>
      </div>

      <AppThemePicker id-prefix="header-theme" />
    </div>
  </header>
</template>
