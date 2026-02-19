<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  status: string;
}>();

const label = computed(() => props.status.replaceAll("_", " "));

const toneClass = computed(() => {
  if (props.status === "success") {
    return "border-state-success-border bg-state-success-bg text-state-success-text";
  }
  if (props.status === "partial_failure") {
    return "border-state-warning-border bg-state-warning-bg text-state-warning-text";
  }
  if (props.status === "failed") {
    return "border-state-danger-border bg-state-danger-bg text-state-danger-text";
  }
  if (props.status === "running") {
    return "border-state-info-border bg-state-info-bg text-state-info-text";
  }
  return "border-stroke-default bg-surface-card-muted text-ink-secondary";
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
