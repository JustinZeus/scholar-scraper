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
    return "border-zinc-300 bg-zinc-100 text-zinc-900 hover:bg-zinc-200 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-zinc-700";
  }

  if (props.variant === "ghost") {
    return "border-zinc-300 bg-transparent text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800";
  }

  if (props.variant === "danger") {
    return "border-rose-300 bg-rose-100 text-rose-800 hover:bg-rose-200 dark:border-rose-800 dark:bg-rose-950/60 dark:text-rose-200 dark:hover:bg-rose-900/70";
  }

  return "border-brand-700 bg-brand-700 text-white hover:bg-brand-600 dark:border-brand-400 dark:bg-brand-400 dark:text-zinc-950 dark:hover:bg-brand-300";
});
</script>

<template>
  <button
    class="inline-flex min-h-10 items-center justify-center rounded-lg border px-3 py-2 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-100 disabled:cursor-not-allowed disabled:opacity-60 dark:focus-visible:ring-brand-400 dark:focus-visible:ring-offset-zinc-950"
    :class="variantClass"
    :type="props.type"
    :disabled="props.disabled"
  >
    <slot />
  </button>
</template>
