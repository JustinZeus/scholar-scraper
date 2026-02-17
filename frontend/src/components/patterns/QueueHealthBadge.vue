<script setup lang="ts">
const props = defineProps<{
  queued: number;
  retrying: number;
  dropped: number;
}>();
</script>

<template>
  <span
    class="inline-flex flex-wrap items-center gap-2 rounded-full border border-zinc-300 bg-zinc-100 px-3 py-1 text-xs text-zinc-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
  >
    <span class="font-medium">Queue</span>
    <span class="rounded-full bg-zinc-200 px-2 py-0.5 dark:bg-zinc-700">{{ props.queued }} queued</span>
    <span class="rounded-full bg-amber-100 px-2 py-0.5 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
      {{ props.retrying }} retrying
    </span>
    <span class="rounded-full bg-rose-100 px-2 py-0.5 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">
      {{ props.dropped }} dropped
    </span>
  </span>
</template>
