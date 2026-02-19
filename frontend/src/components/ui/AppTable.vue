<script setup lang="ts">
defineProps<{
  label?: string;
}>();
</script>

<template>
  <div
    class="max-w-full overflow-x-auto rounded-xl border border-stroke-default focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset"
    tabindex="0"
  >
    <table class="min-w-full border-collapse bg-surface-table text-sm" :aria-label="label || 'Data table'">
      <slot />
    </table>
  </div>
</template>

<style scoped>
:deep(th),
:deep(td) {
  @apply border-b border-stroke-default px-3 py-2 text-left align-top;
}

:deep(th) {
  @apply sticky top-0 z-10 bg-surface-table-header font-semibold text-ink-primary;
}

:deep(td) {
  @apply text-ink-secondary;
}
</style>
