<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import AppAlert from "@/components/ui/AppAlert.vue";
import AppBrandMark from "@/components/ui/AppBrandMark.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppThemePicker from "@/components/ui/AppThemePicker.vue";
import { ApiRequestError } from "@/lib/api/errors";
import { useAuthStore } from "@/stores/auth";

const router = useRouter();
const auth = useAuthStore();

const email = ref("");
const password = ref("");
const pending = ref(false);
const errorMessage = ref<string | null>(null);
const errorRequestId = ref<string | null>(null);
const retryAfterSeconds = ref<number | null>(null);

const canSubmit = computed(
  () => !pending.value && email.value.trim().length > 0 && password.value.length > 0,
);

async function onSubmit(): Promise<void> {
  if (!canSubmit.value) {
    return;
  }

  pending.value = true;
  errorMessage.value = null;
  errorRequestId.value = null;
  retryAfterSeconds.value = null;

  try {
    await auth.login(email.value.trim(), password.value);
    await router.replace({ name: "dashboard" });
  } catch (error) {
    if (error instanceof ApiRequestError) {
      errorMessage.value = error.message;
      errorRequestId.value = error.requestId;
      const details = error.details as { retry_after_seconds?: unknown } | null;
      if (typeof details?.retry_after_seconds === "number") {
        retryAfterSeconds.value = details.retry_after_seconds;
      }
    } else {
      errorMessage.value = "Unable to sign in. Please try again.";
    }
  } finally {
    pending.value = false;
  }
}
</script>

<template>
  <div class="relative h-[100dvh] max-h-[100dvh] overflow-hidden bg-surface-app">
    <div class="absolute right-4 top-4 z-10 sm:right-6 sm:top-6">
      <AppThemePicker compact id-prefix="login-theme" />
    </div>

    <div class="pointer-events-none absolute inset-0">
      <div class="absolute -top-28 right-[-8rem] h-72 w-72 rounded-full bg-brand-300/25 blur-3xl" />
      <div class="absolute bottom-[-8rem] left-[-7rem] h-80 w-80 rounded-full bg-info-300/20 blur-3xl" />
    </div>

    <div class="relative mx-auto grid h-full w-full max-w-md items-center px-4 py-8 sm:px-6">
      <AppCard class="space-y-6 border-stroke-default/80 bg-surface-card/90 p-6 backdrop-blur sm:p-7">
        <div class="grid justify-items-center gap-2 text-center">
          <AppBrandMark size="xl" />
          <p class="font-display text-2xl font-semibold tracking-tight text-ink-primary">scholarr</p>
          <h1 class="text-sm font-medium uppercase tracking-[0.12em] text-ink-secondary">Sign in</h1>
        </div>

        <AppAlert v-if="errorMessage" tone="danger">
          <template #title>Login failed</template>
          <p>{{ errorMessage }}</p>
          <p v-if="retryAfterSeconds !== null" class="text-secondary">Retry after {{ retryAfterSeconds }} seconds.</p>
          <p class="text-secondary">Request ID: {{ errorRequestId || "n/a" }}</p>
        </AppAlert>

        <form class="grid gap-4" @submit.prevent="onSubmit">
          <label class="grid gap-2 text-sm font-medium text-ink-secondary">
            <span>Email</span>
            <AppInput id="login-email" v-model="email" type="email" autocomplete="email" autofocus />
          </label>

          <label class="grid gap-2 text-sm font-medium text-ink-secondary">
            <span>Password</span>
            <AppInput
              id="login-password"
              v-model="password"
              type="password"
              autocomplete="current-password"
            />
          </label>

          <AppButton type="submit" :disabled="!canSubmit" class="w-full justify-center">
            {{ pending ? "Signing in..." : "Sign in" }}
          </AppButton>
        </form>

        <p class="text-center text-xs text-secondary">
          Use your assigned account credentials.
        </p>
      </AppCard>
    </div>
  </div>
</template>
