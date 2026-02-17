<script setup lang="ts">
import AppAlert from "@/components/ui/AppAlert.vue";
import { useUiStore } from "@/stores/ui";

const ui = useUiStore();
</script>

<template>
  <div v-if="ui.globalError" class="sticky top-[4.5rem] z-20 px-4 pb-2 sm:px-6 lg:px-8">
    <div class="mx-auto w-full max-w-7xl">
      <AppAlert tone="danger" :dismissible="true" @dismiss="ui.clearGlobalError()">
        <template #title>Request failed</template>
        <p>{{ ui.globalError.message }}</p>
        <p class="text-secondary">Request ID: {{ ui.globalError.requestId || "n/a" }}</p>
      </AppAlert>
    </div>
  </div>
</template>
