<script setup lang="ts">
import { computed } from "vue";

import AppHelpHint from "@/components/ui/AppHelpHint.vue";
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

const READY_TOOLTIP = "No active cooldown. Scraping can proceed normally.";
const RATE_LIMIT_INTRO =
  "Google Scholar rate-limits automated requests. The cooldown pauses scraping to avoid your IP being blocked.";

const tooltipText = computed(() => {
  if (!props.state.cooldown_active) return READY_TOOLTIP;

  const parts = [RATE_LIMIT_INTRO];
  if (props.state.cooldown_reason_label) {
    parts.push(`Why: ${props.state.cooldown_reason_label}`);
  }
  if (props.state.recommended_action) {
    parts.push(`Action: ${props.state.recommended_action}`);
  }
  return parts.join(" \u2014 ");
});
</script>

<template>
  <span class="inline-flex items-center gap-1">
    <span class="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold" :class="toneClass">
      {{ label }}
    </span>
    <AppHelpHint :text="tooltipText" />
  </span>
</template>
