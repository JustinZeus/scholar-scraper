<script setup lang="ts">
import { computed } from "vue";

import AppButton from "@/components/ui/AppButton.vue";

const props = withDefaults(
  defineProps<{
    tone?: "danger" | "warning" | "info" | "success";
    dismissible?: boolean;
  }>(),
  {
    tone: "info",
    dismissible: false,
  },
);

const emit = defineEmits<{ dismiss: [] }>();

const toneClass = computed(() => {
  if (props.tone === "danger") {
    return "border-rose-300 bg-rose-50 text-rose-900 dark:border-rose-800 dark:bg-rose-950/45 dark:text-rose-200";
  }
  if (props.tone === "warning") {
    return "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/45 dark:text-amber-200";
  }
  if (props.tone === "success") {
    return "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/45 dark:text-emerald-200";
  }
  return "border-brand-300 bg-brand-50 text-brand-900 dark:border-brand-800 dark:bg-brand-950/45 dark:text-brand-200";
});

const alertRole = computed(() => (props.tone === "danger" || props.tone === "warning" ? "alert" : "status"));
const alertLive = computed(() => (props.tone === "danger" || props.tone === "warning" ? "assertive" : "polite"));
</script>

<template>
  <div
    class="flex items-start justify-between gap-3 rounded-xl border px-4 py-3 text-sm"
    :class="toneClass"
    :role="alertRole"
    :aria-live="alertLive"
  >
    <div class="space-y-1">
      <strong v-if="$slots.title" class="block font-semibold"><slot name="title" /></strong>
      <slot />
    </div>
    <AppButton v-if="props.dismissible" variant="ghost" @click="emit('dismiss')">Dismiss</AppButton>
  </div>
</template>
