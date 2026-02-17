<script setup lang="ts">
const props = defineProps<{
  open: boolean;
  title: string;
}>();

const emit = defineEmits<{ close: [] }>();
</script>

<template>
  <div v-if="props.open" class="fixed inset-0 z-50 grid place-items-center bg-zinc-950/60 p-4" @click.self="emit('close')">
    <div class="w-full max-w-lg rounded-2xl border border-zinc-200 bg-white p-6 shadow-panel dark:border-zinc-800 dark:bg-zinc-900">
      <h3 class="mb-4 font-display text-xl font-semibold text-zinc-900 dark:text-zinc-100">{{ props.title }}</h3>
      <slot />
    </div>
  </div>
</template>
