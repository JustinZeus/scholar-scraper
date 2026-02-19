<script setup lang="ts">
import AppAlert from "@/components/ui/AppAlert.vue";

const props = withDefaults(
  defineProps<{
    successMessage?: string | null;
    successTitle?: string;
    errorMessage?: string | null;
    errorRequestId?: string | null;
    errorTitle?: string;
  }>(),
  {
    successMessage: null,
    successTitle: "Operation complete",
    errorMessage: null,
    errorRequestId: null,
    errorTitle: "Request failed",
  },
);

const emit = defineEmits<{
  dismissSuccess: [];
}>();
</script>

<template>
  <div class="space-y-3">
    <AppAlert
      v-if="props.successMessage"
      tone="success"
      dismissible
      @dismiss="emit('dismissSuccess')"
    >
      <template #title>{{ props.successTitle }}</template>
      <p>{{ props.successMessage }}</p>
    </AppAlert>

    <AppAlert v-if="props.errorMessage" tone="danger">
      <template #title>{{ props.errorTitle }}</template>
      <p>{{ props.errorMessage }}</p>
      <p class="text-secondary">Request ID: {{ props.errorRequestId || "n/a" }}</p>
    </AppAlert>
  </div>
</template>
