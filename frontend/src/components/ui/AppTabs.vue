<script setup lang="ts">
export interface AppTabItem {
  id: string;
  label: string;
  disabled?: boolean;
}

const props = defineProps<{
  modelValue: string;
  items: AppTabItem[];
  ariaLabel?: string;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
}>();

function onSelect(tabId: string, disabled: boolean | undefined): void {
  if (disabled || tabId === props.modelValue) {
    return;
  }
  emit("update:modelValue", tabId);
}
</script>

<template>
  <div
    class="flex flex-wrap gap-2 rounded-lg border border-stroke-default bg-surface-card-muted p-2"
    role="tablist"
    :aria-label="props.ariaLabel || 'Tabs'"
  >
    <button
      v-for="item in props.items"
      :key="item.id"
      type="button"
      role="tab"
      :aria-selected="item.id === props.modelValue"
      :tabindex="item.id === props.modelValue ? 0 : -1"
      :disabled="item.disabled"
      class="inline-flex min-h-9 items-center rounded-md border px-3 py-1.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset disabled:cursor-not-allowed disabled:opacity-60"
      :class="
        item.id === props.modelValue
          ? 'border-stroke-interactive bg-surface-nav-active text-ink-primary'
          : 'border-stroke-default bg-surface-card text-ink-secondary hover:border-stroke-interactive hover:text-ink-primary'
      "
      @click="onSelect(item.id, item.disabled)"
    >
      {{ item.label }}
    </button>
  </div>
</template>
