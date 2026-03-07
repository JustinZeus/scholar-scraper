<script setup lang="ts">
defineProps<{
  baselineCompleted: boolean;
  lastRunStatus: string | null;
}>();
</script>

<template>
  <span
    v-if="!baselineCompleted"
    class="ml-1.5 inline-flex items-center rounded-full border border-state-warning-border bg-state-warning-bg px-1.5 py-0.5 text-[10px] font-medium text-state-warning-text"
    title="This scholar hasn't been scraped yet. Publications will appear after the next run."
  >Pending</span>
  <span
    v-if="lastRunStatus === 'failed'"
    class="ml-1.5 inline-flex items-center rounded-full border border-state-danger-border bg-state-danger-bg px-1.5 py-0.5 text-[10px] font-medium text-state-danger-text"
    title="The last scrape run for this scholar failed."
  >Failed</span>
  <span
    v-else-if="lastRunStatus === 'partial'"
    class="ml-1.5 inline-flex items-center rounded-full border border-state-warning-border bg-state-warning-bg px-1.5 py-0.5 text-[10px] font-medium text-state-warning-text"
    title="The last scrape run for this scholar completed with partial results."
  >Partial</span>
  <span
    v-else-if="lastRunStatus === 'success'"
    class="ml-1.5 inline-flex items-center rounded-full border border-state-success-border bg-state-success-bg px-1.5 py-0.5 text-[10px] font-medium text-state-success-text"
    title="The last scrape run for this scholar completed successfully."
  >OK</span>
</template>
