<script setup lang="ts">
import AppButton from "@/components/ui/AppButton.vue";
import AppModal from "@/components/ui/AppModal.vue";

withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    message: string;
    confirmLabel?: string;
    cancelLabel?: string;
    variant?: "danger" | "default";
  }>(),
  { confirmLabel: "Confirm", cancelLabel: "Cancel", variant: "default" },
);

const emit = defineEmits<{ confirm: []; cancel: [] }>();
</script>

<template>
  <AppModal :open="open" :title="title" @close="emit('cancel')">
    <p class="mb-6 text-sm text-secondary">{{ message }}</p>
    <div class="flex justify-end gap-2">
      <AppButton variant="secondary" @click="emit('cancel')">{{ cancelLabel }}</AppButton>
      <AppButton :variant="variant === 'danger' ? 'danger' : 'primary'" @click="emit('confirm')">{{ confirmLabel }}</AppButton>
    </div>
  </AppModal>
</template>
