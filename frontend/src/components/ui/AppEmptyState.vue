<script setup lang="ts">
defineProps<{
  title: string;
  body: string;
}>();
</script>

<template>
  <section class="rounded-xl border border-dashed border-zinc-300 bg-zinc-50 p-5 dark:border-zinc-700 dark:bg-zinc-900/60">
    <h3 class="font-display text-lg font-semibold text-zinc-900 dark:text-zinc-100">{{ title }}</h3>
    <p class="mt-1 text-sm text-zinc-600 dark:text-zinc-400">{{ body }}</p>
    <div v-if="$slots.default" class="mt-4">
      <slot />
    </div>
  </section>
</template>
