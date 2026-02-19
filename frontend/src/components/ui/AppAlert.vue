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
    return "border-state-danger-border bg-state-danger-bg text-state-danger-text";
  }
  if (props.tone === "warning") {
    return "border-state-warning-border bg-state-warning-bg text-state-warning-text";
  }
  if (props.tone === "success") {
    return "border-state-success-border bg-state-success-bg text-state-success-text";
  }
  return "border-state-info-border bg-state-info-bg text-state-info-text";
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
