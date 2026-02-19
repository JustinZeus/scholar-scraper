<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import AppAlert from "@/components/ui/AppAlert.vue";
import {
  formatCooldownCountdown,
  type ScrapeSafetyState,
} from "@/features/safety";

const props = withDefaults(
  defineProps<{
    safetyState: ScrapeSafetyState;
    manualRunAllowed?: boolean;
  }>(),
  {
    manualRunAllowed: true,
  },
);

const now = ref(Date.now());
let timer: ReturnType<typeof setInterval> | null = null;

const cooldownUntilMs = computed(() => {
  if (!props.safetyState.cooldown_until) {
    return null;
  }
  const parsed = new Date(props.safetyState.cooldown_until).getTime();
  if (Number.isNaN(parsed)) {
    return null;
  }
  return parsed;
});

const cooldownRemainingSeconds = computed(() => {
  if (!props.safetyState.cooldown_active) {
    return 0;
  }

  if (cooldownUntilMs.value !== null) {
    return Math.max(0, Math.floor((cooldownUntilMs.value - now.value) / 1000));
  }

  return Math.max(0, props.safetyState.cooldown_remaining_seconds || 0);
});

const isCooldownBlocked = computed(() => props.safetyState.cooldown_active && cooldownRemainingSeconds.value > 0);
const isPolicyBlocked = computed(() => !props.manualRunAllowed);

const isVisible = computed(() => isPolicyBlocked.value || isCooldownBlocked.value);
const tone = computed(() => {
  if (isPolicyBlocked.value) {
    return "warning" as const;
  }
  if (props.safetyState.cooldown_reason === "blocked_failure_threshold_exceeded") {
    return "danger" as const;
  }
  return "warning" as const;
});

const title = computed(() => {
  if (isPolicyBlocked.value) {
    return "Manual checks disabled by server policy";
  }
  return props.safetyState.cooldown_reason_label || "Safety cooldown active";
});

const detailText = computed(() => {
  if (isPolicyBlocked.value) {
    return "This server currently disallows manual checks. Automatic checks may still run if enabled by policy.";
  }
  const countdown = formatCooldownCountdown(cooldownRemainingSeconds.value);
  return `Manual and scheduled checks are paused for ${countdown}.`;
});

const actionText = computed(() => {
  if (isPolicyBlocked.value) {
    return "Ask an admin to enable manual checks in server environment policy.";
  }
  return props.safetyState.recommended_action;
});

onMounted(() => {
  timer = setInterval(() => {
    now.value = Date.now();
  }, 1000);
});

onBeforeUnmount(() => {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
});
</script>

<template>
  <AppAlert v-if="isVisible" :tone="tone">
    <template #title>{{ title }}</template>
    <p>{{ detailText }}</p>
    <p v-if="actionText" class="text-secondary">{{ actionText }}</p>
  </AppAlert>
</template>
