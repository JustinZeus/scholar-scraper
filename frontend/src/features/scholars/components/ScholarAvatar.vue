<script setup lang="ts">
import { computed, ref, watch } from "vue";

const props = withDefaults(
  defineProps<{
    label?: string | null;
    scholarId: string;
    imageUrl?: string | null;
    size?: "sm" | "md";
  }>(),
  {
    label: null,
    imageUrl: null,
    size: "md",
  },
);

const imageFailed = ref(false);

watch(
  () => props.imageUrl,
  () => {
    imageFailed.value = false;
  },
);

const initials = computed(() => {
  const source = (props.label || "").trim();
  if (!source) {
    return props.scholarId.slice(0, 2).toUpperCase();
  }

  const tokens = source.split(/\s+/).filter(Boolean);
  if (tokens.length === 1) {
    return tokens[0].slice(0, 2).toUpperCase();
  }
  return `${tokens[0].charAt(0)}${tokens[1].charAt(0)}`.toUpperCase();
});

const containerClass = computed(() =>
  props.size === "sm" ? "h-10 w-10 text-[11px]" : "h-12 w-12 text-xs",
);

const canRenderImage = computed(() => Boolean(props.imageUrl) && !imageFailed.value);

function onImageError(): void {
  imageFailed.value = true;
}
</script>

<template>
  <div
    class="flex shrink-0 items-center justify-center overflow-hidden rounded-full border border-stroke-default bg-surface-card-muted font-semibold text-ink-secondary"
    :class="containerClass"
  >
    <img
      v-if="canRenderImage"
      :src="props.imageUrl || ''"
      :alt="`${props.label || props.scholarId} profile image`"
      class="h-full w-full object-cover"
      loading="lazy"
      referrerpolicy="no-referrer"
      @error="onImageError"
    />
    <span v-else>{{ initials }}</span>
  </div>
</template>
