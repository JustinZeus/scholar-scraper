<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    title: string;
    subtitle?: string;
    fill?: boolean;
  }>(),
  {
    fill: false,
  },
);
</script>

<template>
  <section
    :class="
      props.fill
        ? 'min-w-0 flex min-h-0 flex-col gap-6 lg:h-full'
        : 'page-stack min-w-0'
    "
  >
    <header class="space-y-2">
      <h1 class="page-title">{{ props.title }}</h1>
      <p v-if="props.subtitle" class="page-subtitle">{{ props.subtitle }}</p>
    </header>
    <div v-if="props.fill" class="min-h-0 flex-1">
      <slot />
    </div>
    <slot v-else />
  </section>
</template>
