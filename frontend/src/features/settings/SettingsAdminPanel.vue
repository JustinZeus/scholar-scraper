<script setup lang="ts">
import { nextTick, onMounted, watch } from "vue";
import { ref } from "vue";

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

const { errorMessage, errorRequestId, successMessage, clearAlerts, assignError } = useRequestState();

const usersRef = ref<InstanceType<typeof AdminUsersSection> | null>(null);
const integrityRef = ref<InstanceType<typeof AdminIntegritySection> | null>(null);
const repairsRef = ref<InstanceType<typeof AdminRepairsSection> | null>(null);
const pdfQueueRef = ref<InstanceType<typeof AdminPdfQueueSection> | null>(null);

async function loadSection(): Promise<void> {
  clearAlerts();
  try {
    if (props.section === SECTION_USERS && usersRef.value) {
      await usersRef.value.load();
    } else if (props.section === SECTION_INTEGRITY && integrityRef.value) {
      await integrityRef.value.load();
    } else if (props.section === SECTION_REPAIRS) {
      await usersRef.value?.load();
      await repairsRef.value?.load();
    } else if (props.section === SECTION_PDF && pdfQueueRef.value) {
      await pdfQueueRef.value.load();
    }
  } catch (error) {
    assignError(error, "Unable to load admin data.");
  }
}

onMounted(() => {
  nextTick(loadSection);
});
watch(() => props.section, loadSection, { flush: "post" });
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

    <AdminUsersSection v-if="props.section === SECTION_USERS || props.section === SECTION_REPAIRS" v-show="props.section === SECTION_USERS" ref="usersRef" />
    <AdminIntegritySection v-if="props.section === SECTION_INTEGRITY" ref="integrityRef" />
    <AdminRepairsSection v-if="props.section === SECTION_REPAIRS" ref="repairsRef" :users="usersRef?.users ?? []" />
    <AdminPdfQueueSection v-if="props.section === SECTION_PDF" ref="pdfQueueRef" />
  </section>
</template>
