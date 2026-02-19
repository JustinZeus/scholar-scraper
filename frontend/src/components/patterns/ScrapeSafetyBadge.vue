<script setup lang="ts">
import { computed } from "vue";

import { type ScrapeSafetyState } from "@/features/safety";

const props = defineProps<{
  state: ScrapeSafetyState;
}>();

const label = computed(() => (props.state.cooldown_active ? "Safety cooldown" : "Safety ready"));

const toneClass = computed(() => {
  if (!props.state.cooldown_active) {
    return "border-state-success-border bg-state-success-bg text-state-success-text";
  }
  if (props.state.cooldown_reason === "blocked_failure_threshold_exceeded") {
    return "border-state-danger-border bg-state-danger-bg text-state-danger-text";
  }
  return "border-state-warning-border bg-state-warning-bg text-state-warning-text";
});
</script>

<template>
  <span class="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold" :class="toneClass">
    {{ label }}
  </span>
</template>
