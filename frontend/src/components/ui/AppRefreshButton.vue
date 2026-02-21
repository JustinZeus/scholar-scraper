<script setup lang="ts">
import { computed } from "vue";

import AppButton from "@/components/ui/AppButton.vue";

const props = withDefaults(
  defineProps<{
    disabled?: boolean;
    loading?: boolean;
    title?: string;
    loadingTitle?: string;
    variant?: "primary" | "secondary" | "ghost" | "danger";
    size?: "md" | "sm";
  }>(),
  {
    disabled: false,
    loading: false,
    title: "Refresh",
    loadingTitle: "Refreshing",
    variant: "secondary",
    size: "md",
  },
);

const resolvedTitle = computed(() => (props.loading ? props.loadingTitle : props.title));
const isDisabled = computed(() => props.disabled || props.loading);
const buttonSizeClass = computed(() => {
  if (props.size === "sm") {
    return "min-h-8 h-8 w-8";
  }
  return "min-h-10 h-10 w-10";
});
const iconSizeClass = computed(() => (props.size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"));
</script>

<template>
  <AppButton
    :variant="props.variant"
    :disabled="isDisabled"
    class="rounded-full p-0"
    :class="buttonSizeClass"
    :title="resolvedTitle"
    :aria-label="resolvedTitle"
  >
    <span class="sr-only">{{ resolvedTitle }}</span>
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.8"
      :class="[iconSizeClass, props.loading ? 'animate-spin' : '']"
      aria-hidden="true"
    >
      <path d="M20 4v6h-6" />
      <path d="M4 20v-6h6" />
      <path d="M6.5 9A7.5 7.5 0 0 1 19 7.5L20 10" />
      <path d="M17.5 15A7.5 7.5 0 0 1 5 16.5L4 14" />
    </svg>
  </AppButton>
</template>
