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
    class="w-full rounded-lg border border-stroke-interactive bg-surface-input px-3 py-2 text-sm text-ink-primary outline-none transition focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset disabled:cursor-not-allowed disabled:opacity-60"
    :id="id"
    :disabled="disabled"
  >
    <slot />
  </select>
</template>
