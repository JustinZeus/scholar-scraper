<script setup lang="ts">
import AppEmptyState from "@/components/ui/AppEmptyState.vue";
import AppSkeleton from "@/components/ui/AppSkeleton.vue";

const props = withDefaults(
  defineProps<{
    loading: boolean;
    loadingLines?: number;
    empty?: boolean;
    emptyTitle?: string;
    emptyBody?: string;
    showEmpty?: boolean;
  }>(),
  {
    loadingLines: 6,
    empty: false,
    emptyTitle: "No data available",
    emptyBody: "No records matched this request.",
    showEmpty: true,
  },
);
</script>

<template>
  <AppSkeleton v-if="props.loading" :lines="props.loadingLines" />
  <AppEmptyState
    v-else-if="props.showEmpty && props.empty"
    :title="props.emptyTitle"
    :body="props.emptyBody"
  >
    <slot name="empty" />
  </AppEmptyState>
  <slot v-else />
</template>
