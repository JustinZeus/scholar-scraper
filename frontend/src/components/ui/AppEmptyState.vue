<script setup lang="ts">
defineProps<{
  title: string;
  body: string;
}>();
</script>

<template>
  <section class="rounded-xl border border-dashed border-stroke-interactive bg-surface-card-muted p-5">
    <h3 class="font-display text-lg font-semibold text-ink-primary">{{ title }}</h3>
    <p class="mt-1 text-sm text-ink-secondary">{{ body }}</p>
    <div v-if="$slots.default" class="mt-4">
      <slot />
    </div>
  </section>
</template>
