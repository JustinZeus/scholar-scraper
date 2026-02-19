<script setup lang="ts">
const props = defineProps<{
  queued: number;
  retrying: number;
  dropped: number;
}>();
</script>

<template>
  <span
    class="inline-flex flex-wrap items-center gap-2 rounded-xl border border-stroke-default bg-surface-card-muted/90 px-3 py-1.5 text-xs text-ink-secondary"
  >
    <span class="font-semibold tracking-wide text-ink-primary">Queue</span>
    <span class="inline-flex items-center gap-1 rounded-full bg-surface-card px-2 py-0.5">
      <span class="h-1.5 w-1.5 rounded-full bg-ink-muted" />
      {{ props.queued }} queued
    </span>
    <span class="inline-flex items-center gap-1 rounded-full bg-state-warning-bg px-2 py-0.5 text-state-warning-text">
      <span class="h-1.5 w-1.5 rounded-full bg-warning-500" />
      {{ props.retrying }} retrying
    </span>
    <span class="inline-flex items-center gap-1 rounded-full bg-state-danger-bg px-2 py-0.5 text-state-danger-text">
      <span class="h-1.5 w-1.5 rounded-full bg-danger-500" />
      {{ props.dropped }} dropped
    </span>
  </span>
</template>
