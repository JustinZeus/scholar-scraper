<script setup lang="ts">
const props = defineProps<{
  open: boolean;
  title: string;
}>();

const emit = defineEmits<{ close: [] }>();
</script>

<template>
  <div v-if="props.open" class="fixed inset-0 z-50 grid place-items-center bg-surface-overlay/60 p-4" @click.self="emit('close')">
    <div class="w-full max-w-lg rounded-2xl border border-stroke-default bg-surface-card p-6 shadow-panel">
      <h3 class="mb-4 font-display text-xl font-semibold text-ink-primary">{{ props.title }}</h3>
      <slot />
    </div>
  </div>
</template>
