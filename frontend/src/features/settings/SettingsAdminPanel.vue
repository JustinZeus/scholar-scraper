<script setup lang="ts">
import { onMounted, ref, watch } from "vue";

import AsyncStateGate from "@/components/patterns/AsyncStateGate.vue";
import RequestStateAlerts from "@/components/patterns/RequestStateAlerts.vue";
import AdminIntegritySection from "@/features/settings/components/AdminIntegritySection.vue";
import AdminPdfQueueSection from "@/features/settings/components/AdminPdfQueueSection.vue";
import AdminRepairsSection from "@/features/settings/components/AdminRepairsSection.vue";
import AdminUsersSection from "@/features/settings/components/AdminUsersSection.vue";
import { useRequestState } from "@/composables/useRequestState";

const SECTION_USERS = "users";
const SECTION_INTEGRITY = "integrity";
const SECTION_REPAIRS = "repairs";
const SECTION_PDF = "pdf";

const props = defineProps<{
  section: "users" | "integrity" | "repairs" | "pdf";
}>();

const loading = ref(true);
const { errorMessage, errorRequestId, successMessage, clearAlerts, assignError } = useRequestState();

const usersRef = ref<InstanceType<typeof AdminUsersSection> | null>(null);
const integrityRef = ref<InstanceType<typeof AdminIntegritySection> | null>(null);
const repairsRef = ref<InstanceType<typeof AdminRepairsSection> | null>(null);
const pdfQueueRef = ref<InstanceType<typeof AdminPdfQueueSection> | null>(null);

async function refreshForSection(): Promise<void> {
  if (props.section === SECTION_USERS && usersRef.value) {
    await usersRef.value.load();
    return;
  }
  if (props.section === SECTION_INTEGRITY && integrityRef.value) {
    await integrityRef.value.load();
    return;
  }
  if (props.section === SECTION_REPAIRS) {
    await Promise.all([
      usersRef.value?.load(),
      repairsRef.value?.load(),
    ]);
    return;
  }
  if (props.section === SECTION_PDF && pdfQueueRef.value) {
    await pdfQueueRef.value.load();
  }
}

async function loadSection(): Promise<void> {
  loading.value = true;
  clearAlerts();
  try {
    await refreshForSection();
  } catch (error) {
    assignError(error, "Unable to load admin data.");
  } finally {
    loading.value = false;
  }
}

onMounted(loadSection);
watch(() => props.section, loadSection);
</script>

<template>
  <section class="grid gap-4">
    <RequestStateAlerts
      :success-message="successMessage"
      :error-message="errorMessage"
      :error-request-id="errorRequestId"
      success-title="Operation complete"
      error-title="Operation failed"
      @dismiss-success="successMessage = null"
    />

    <AsyncStateGate :loading="loading" :loading-lines="10" :show-empty="false">
      <AdminUsersSection v-if="props.section === SECTION_USERS || props.section === SECTION_REPAIRS" v-show="props.section === SECTION_USERS" ref="usersRef" />
      <AdminIntegritySection v-if="props.section === SECTION_INTEGRITY" ref="integrityRef" />
      <AdminRepairsSection v-if="props.section === SECTION_REPAIRS" ref="repairsRef" :users="usersRef?.users ?? []" />
      <AdminPdfQueueSection v-if="props.section === SECTION_PDF" ref="pdfQueueRef" />
    </AsyncStateGate>
  </section>
</template>
