<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  tone?: "neutral" | "success" | "warning" | "danger" | "info";
}>();

const toneClass = computed(() => {
  if (props.tone === "success") {
    return "border-state-success-border bg-state-success-bg text-state-success-text";
  }

  if (props.tone === "warning") {
    return "border-state-warning-border bg-state-warning-bg text-state-warning-text";
  }

  if (props.tone === "danger") {
    return "border-state-danger-border bg-state-danger-bg text-state-danger-text";
  }

  if (props.tone === "info") {
    return "border-state-info-border bg-state-info-bg text-state-info-text";
  }

  return "border-stroke-default bg-surface-card-muted text-ink-secondary";
});
</script>

<template>
  <span class="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium" :class="toneClass">
    <slot />
  </span>
</template>
