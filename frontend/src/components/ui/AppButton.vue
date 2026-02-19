<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    variant?: "primary" | "secondary" | "ghost" | "danger";
    type?: "button" | "submit" | "reset";
    disabled?: boolean;
  }>(),
  {
    variant: "primary",
    type: "button",
    disabled: false,
  },
);

const variantClass = computed(() => {
  if (props.variant === "secondary") {
    return "border-action-secondary-border bg-action-secondary-bg text-action-secondary-text shadow-sm hover:border-action-secondary-hover-border hover:bg-action-secondary-hover-bg hover:text-action-secondary-hover-text";
  }

  if (props.variant === "ghost") {
    return "border-action-ghost-border bg-action-ghost-bg text-action-ghost-text hover:border-action-ghost-hover-border hover:bg-action-ghost-hover-bg hover:text-action-ghost-hover-text";
  }

  if (props.variant === "danger") {
    return "border-action-danger-border bg-action-danger-bg text-action-danger-text shadow-sm hover:border-action-danger-hover-border hover:bg-action-danger-hover-bg hover:text-action-danger-hover-text";
  }

  return "border-action-primary-border bg-action-primary-bg text-action-primary-text shadow-sm hover:border-action-primary-hover-border hover:bg-action-primary-hover-bg hover:text-action-primary-hover-text";
});
</script>

<template>
  <button
    class="inline-flex min-h-10 items-center justify-center rounded-lg border px-3 py-2 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset disabled:cursor-not-allowed disabled:opacity-60"
    :class="variantClass"
    :type="props.type"
    :disabled="props.disabled"
  >
    <slot />
  </button>
</template>
