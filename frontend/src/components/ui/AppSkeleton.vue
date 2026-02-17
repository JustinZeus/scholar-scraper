<script setup lang="ts">
defineProps<{
  lines?: number;
}>();
</script>

<template>
  <div class="space-y-2" role="status" aria-live="polite">
    <span
      v-for="line in lines || 3"
      :key="line"
      class="block h-3 animate-pulse rounded-full bg-zinc-200 dark:bg-zinc-800"
    />
  </div>
</template>
