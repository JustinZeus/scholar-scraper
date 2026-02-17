<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  status: string;
}>();

const label = computed(() => props.status.replaceAll("_", " "));

const toneClass = computed(() => {
  if (props.status === "success") {
    return "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300";
  }
  if (props.status === "partial_failure") {
    return "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-300";
  }
  if (props.status === "failed") {
    return "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950/50 dark:text-rose-300";
  }
  if (props.status === "running") {
    return "border-brand-300 bg-brand-50 text-brand-700 dark:border-brand-800 dark:bg-brand-950/50 dark:text-brand-300";
  }
  return "border-zinc-300 bg-zinc-100 text-zinc-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";
});
</script>

<template>
  <span
    class="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold capitalize"
    :class="toneClass"
  >
    {{ label }}
  </span>
</template>
