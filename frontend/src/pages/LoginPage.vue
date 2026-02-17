<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import AppAlert from "@/components/ui/AppAlert.vue";
import AppButton from "@/components/ui/AppButton.vue";
import AppCard from "@/components/ui/AppCard.vue";
import AppInput from "@/components/ui/AppInput.vue";
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
  <div class="relative min-h-screen overflow-hidden bg-zinc-100 dark:bg-zinc-950">
    <div class="pointer-events-none absolute inset-0">
      <div class="absolute -top-20 left-[-8rem] h-72 w-72 rounded-full bg-brand-300/35 blur-3xl dark:bg-brand-900/35" />
      <div class="absolute bottom-[-7rem] right-[-6rem] h-80 w-80 rounded-full bg-emerald-300/25 blur-3xl dark:bg-emerald-900/25" />
      <div class="absolute left-1/3 top-1/3 h-52 w-52 rounded-full bg-amber-300/20 blur-3xl dark:bg-amber-900/20" />
    </div>

    <div
      class="relative mx-auto grid min-h-screen w-full max-w-6xl items-center gap-8 px-4 py-10 sm:px-6 lg:grid-cols-[minmax(0,1fr)_26rem] lg:px-8"
    >
      <section class="hidden space-y-5 lg:block">
        <p class="inline-flex items-center rounded-full border border-zinc-300 bg-white/70 px-3 py-1 text-xs font-medium uppercase tracking-[0.12em] text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900/70 dark:text-zinc-300">
          Scholarr Control Center
        </p>
        <h1 class="max-w-xl font-display text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
          Scholar tracking with reliable operational controls.
        </h1>
        <p class="max-w-xl text-base leading-relaxed text-zinc-600 dark:text-zinc-400">
          Use your account to review ingestion runs, publication changes, and continuation queue diagnostics from a
          single workspace.
        </p>
        <ul class="grid max-w-xl gap-2 text-sm text-zinc-600 dark:text-zinc-400">
          <li class="rounded-lg border border-zinc-200 bg-white/60 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900/60">
            Session-based authentication with CSRF enforcement.
          </li>
          <li class="rounded-lg border border-zinc-200 bg-white/60 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900/60">
            Run and queue diagnostics are available for support workflows.
          </li>
          <li class="rounded-lg border border-zinc-200 bg-white/60 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900/60">
            Theme-aware interface with light and dark mode support.
          </li>
        </ul>
      </section>

      <AppCard class="w-full max-w-md justify-self-end space-y-6 border-zinc-200/80 bg-white/90 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/85">
        <div class="space-y-2">
          <h1 class="font-display text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">Sign In</h1>
          <p class="text-sm text-secondary">
            Sign in to access scholar tracking, publication updates, and run diagnostics.
          </p>
        </div>

        <AppAlert v-if="errorMessage" tone="danger">
          <template #title>Login failed</template>
          <p>{{ errorMessage }}</p>
          <p v-if="retryAfterSeconds !== null" class="text-secondary">Retry after {{ retryAfterSeconds }} seconds.</p>
          <p class="text-secondary">Request ID: {{ errorRequestId || "n/a" }}</p>
        </AppAlert>

        <form class="grid gap-4" @submit.prevent="onSubmit">
          <label class="grid gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
            <span>Email</span>
            <AppInput id="login-email" v-model="email" type="email" autocomplete="email" />
          </label>

          <label class="grid gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
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
      </AppCard>
    </div>
  </div>
</template>
