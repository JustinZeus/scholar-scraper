<script setup lang="ts">
const model = defineModel<boolean>({ default: false });

defineProps<{
  id?: string;
  disabled?: boolean;
  label?: string;
}>();
</script>

<template>
  <label class="inline-flex min-h-10 items-center gap-2 text-sm text-zinc-800 dark:text-zinc-200" :for="id">
    <input
      :id="id"
      v-model="model"
      class="h-4 w-4 rounded border-zinc-400 text-brand-600 focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-100 dark:border-zinc-600 dark:bg-zinc-900 dark:focus-visible:ring-brand-400 dark:focus-visible:ring-offset-zinc-950"
      type="checkbox"
      :disabled="disabled"
    />
    <span><slot>{{ label }}</slot></span>
  </label>
</template>
