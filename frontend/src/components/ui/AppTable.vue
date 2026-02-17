<script setup lang="ts">
defineProps<{
  label?: string;
}>();
</script>

<template>
  <div
    class="max-w-full overflow-x-auto rounded-xl border border-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-100 dark:border-zinc-800 dark:focus-visible:ring-brand-400 dark:focus-visible:ring-offset-zinc-950"
    tabindex="0"
  >
    <table class="min-w-full border-collapse bg-white text-sm dark:bg-zinc-900" :aria-label="label || 'Data table'">
      <slot />
    </table>
  </div>
</template>

<style scoped>
:deep(th),
:deep(td) {
  @apply border-b border-zinc-200 px-3 py-2 text-left align-top dark:border-zinc-800;
}

:deep(th) {
  @apply sticky top-0 z-10 bg-zinc-100 font-semibold text-zinc-800 dark:bg-zinc-900 dark:text-zinc-200;
}

:deep(td) {
  @apply text-zinc-700 dark:text-zinc-300;
}
</style>
