<script setup lang="ts">
import AppButton from "@/components/ui/AppButton.vue";
import AppHelpHint from "@/components/ui/AppHelpHint.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppRefreshButton from "@/components/ui/AppRefreshButton.vue";
import AppSelect from "@/components/ui/AppSelect.vue";
import type { PublicationMode } from "@/features/publications";
import type { ScholarProfile } from "@/features/scholars";

defineProps<{
  mode: PublicationMode;
  selectedScholarFilter: string;
  searchQuery: string;
  favoriteOnly: boolean;
  actionBusy: boolean;
  loading: boolean;
  scholars: ScholarProfile[];
  startRunDisabled: boolean;
  startRunDisabledReason: string | null;
  startRunButtonLabel: string;
}>();

const emit = defineEmits<{
  (e: "update:mode", value: PublicationMode): void;
  (e: "update:selectedScholarFilter", value: string): void;
  (e: "update:searchQuery", value: string): void;
  (e: "mode-changed"): void;
  (e: "scholar-filter-changed"): void;
  (e: "favorite-only-changed"): void;
  (e: "reset-search"): void;
  (e: "start-run"): void;
  (e: "refresh"): void;
}>();

function scholarLabel(item: ScholarProfile): string {
  return item.display_name || item.scholar_id;
}
</script>

<template>
  <div class="grid gap-3 xl:grid-cols-[minmax(0,13rem)_minmax(0,18rem)_minmax(0,1fr)_auto] xl:items-end">
    <div class="grid gap-1 text-xs text-secondary">
      <div class="flex items-center gap-1">
        <span>Status</span>
        <AppHelpHint text="All shows full history. Unread and New narrow the dataset before search." />
      </div>
      <AppSelect
        :model-value="mode"
        :disabled="actionBusy"
        @update:model-value="emit('update:mode', $event as PublicationMode)"
        @change="emit('mode-changed')"
      >
        <option value="all">All records</option>
        <option value="unread">Unread</option>
        <option value="latest">New (latest run)</option>
      </AppSelect>
    </div>

    <label class="grid gap-1 text-xs text-secondary" for="publications-scholar-filter">
      <span class="inline-flex items-center gap-1">
        Scholar
        <AppHelpHint text="Filter to one tracked scholar profile. Filter is synced to URL query." />
      </span>
      <AppSelect
        id="publications-scholar-filter"
        :model-value="selectedScholarFilter"
        :disabled="actionBusy"
        @update:model-value="emit('update:selectedScholarFilter', $event as string)"
        @change="emit('scholar-filter-changed')"
      >
        <option value="">All scholars</option>
        <option v-for="scholar in scholars" :key="scholar.id" :value="String(scholar.id)">
          {{ scholarLabel(scholar) }}
        </option>
      </AppSelect>
    </label>

    <label class="grid gap-1 text-xs text-secondary" for="publications-search-input">
      <span class="inline-flex items-center gap-1">
        Search
        <AppHelpHint text="Searches title, scholar name, and venue." />
      </span>
      <div class="flex min-w-0 items-center gap-2">
        <AppInput
          id="publications-search-input"
          :model-value="searchQuery"
          placeholder="Search title, scholar, venue, year"
          :disabled="loading"
          @update:model-value="emit('update:searchQuery', $event as string)"
        />
        <AppButton
          v-if="searchQuery.trim().length > 0"
          variant="secondary"
          class="shrink-0"
          :disabled="loading"
          @click="emit('reset-search')"
        >
          Clear
        </AppButton>
      </div>
    </label>

    <div class="flex flex-wrap items-end justify-end gap-2">
      <button
        type="button"
        class="favorite-filter-button"
        :class="favoriteOnly ? 'favorite-filter-on' : 'favorite-filter-off'"
        :disabled="actionBusy"
        :title="favoriteOnly ? 'Favorites-only filter is active' : 'Show only favorites'"
        :aria-pressed="favoriteOnly"
        :aria-label="favoriteOnly ? 'Disable favorites-only filter' : 'Enable favorites-only filter'"
        @click="emit('favorite-only-changed')"
      >
        <span aria-hidden="true">{{ favoriteOnly ? "★" : "☆" }}</span>
      </button>
      <AppButton
        variant="secondary"
        :disabled="startRunDisabled"
        :title="startRunDisabledReason || undefined"
        @click="emit('start-run')"
      >
        {{ startRunButtonLabel }}
      </AppButton>
      <AppRefreshButton
        variant="ghost"
        :disabled="loading"
        :loading="loading"
        title="Refresh publications"
        loading-title="Refreshing publications"
        @click="emit('refresh')"
      />
    </div>
  </div>
</template>

<style scoped>
.favorite-filter-button {
  @apply inline-flex min-h-10 h-10 w-10 items-center justify-center rounded-full border text-base leading-none transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset disabled:cursor-not-allowed disabled:opacity-50;
}

.favorite-filter-on {
  @apply border-warning-300 bg-warning-100 text-warning-700 hover:bg-warning-200;
}

.favorite-filter-off {
  @apply border-stroke-default bg-surface-card-muted text-ink-muted hover:border-stroke-interactive hover:text-ink-secondary;
}
</style>
