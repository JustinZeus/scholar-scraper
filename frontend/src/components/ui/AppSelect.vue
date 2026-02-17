<script setup lang="ts">
const model = defineModel<string>({ default: "" });

defineProps<{
  id?: string;
  disabled?: boolean;
}>();
</script>

<template>
  <select
    v-model="model"
    class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 outline-none ring-brand-300 transition focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:ring-brand-400 dark:focus-visible:ring-offset-zinc-950"
    :id="id"
    :disabled="disabled"
  >
    <slot />
  </select>
</template>
