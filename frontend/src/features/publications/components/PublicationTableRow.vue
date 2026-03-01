<script setup lang="ts">
import AppBadge from "@/components/ui/AppBadge.vue";
import type { PublicationItem } from "@/features/publications";

const props = defineProps<{
  item: PublicationItem;
  itemKey: string;
  selected: boolean;
  favoriteUpdating: boolean;
  retrying: boolean;
  canRetry: boolean;
}>();

const emit = defineEmits<{
  (e: "toggle-selection", event: Event): void;
  (e: "toggle-favorite"): void;
  (e: "retry-pdf"): void;
}>();

function primaryUrl(): string | null {
  return props.item.pub_url || props.item.pdf_url;
}

function identifierUrl(): string | null {
  return props.item.display_identifier?.url ?? null;
}

function identifierLabel(): string | null {
  return props.item.display_identifier?.label ?? null;
}

function pdfPendingLabel(): string {
  if (props.item.pdf_status === "queued") return "Queued";
  if (props.item.pdf_status === "running") return "Resolving...";
  if (props.item.pdf_status === "failed") return "Missing";
  return "Untracked";
}

function formatDate(value: string): string {
  const asDate = new Date(value);
  if (Number.isNaN(asDate.getTime())) return value;
  return asDate.toLocaleDateString();
}
</script>

<template>
  <tr>
    <td>
      <input
        type="checkbox"
        class="h-4 w-4 rounded border-stroke-interactive bg-surface-input text-brand-600 focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset"
        :checked="selected"
        :disabled="item.is_read"
        :aria-label="`Select publication ${item.title}`"
        @change="emit('toggle-selection', $event)"
      />
    </td>
    <td>
      <button
        type="button"
        class="favorite-star-button"
        :class="item.is_favorite ? 'favorite-star-on' : 'favorite-star-off'"
        :aria-label="item.is_favorite ? `Remove ${item.title} from favorites` : `Add ${item.title} to favorites`"
        :aria-pressed="item.is_favorite"
        :disabled="favoriteUpdating"
        @click="emit('toggle-favorite')"
      >
        {{ item.is_favorite ? "★" : "☆" }}
      </button>
    </td>
    <td class="max-w-0">
      <div class="grid min-w-0 gap-1">
        <a
          v-if="primaryUrl()"
          :href="primaryUrl() || ''"
          target="_blank"
          rel="noreferrer"
          class="link-inline block truncate font-medium"
          :title="item.title"
        >
          {{ item.title }}
        </a>
        <span v-else class="block truncate font-medium" :title="item.title">{{ item.title }}</span>
        <a
          v-if="identifierUrl()"
          :href="identifierUrl() || ''"
          target="_blank"
          rel="noreferrer"
          class="link-inline block truncate text-xs"
          :title="identifierLabel() || ''"
        >
          {{ identifierLabel() }}
        </a>
      </div>
    </td>
    <td>
      <span class="block truncate" :title="item.scholar_label">{{ item.scholar_label }}</span>
    </td>
    <td class="whitespace-nowrap">
      <a
        v-if="item.pdf_url"
        :href="item.pdf_url"
        target="_blank"
        rel="noreferrer"
        class="pdf-link-button"
        title="Open PDF"
      >
        <svg class="mr-1 h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
        </svg>
        Available
      </a>
      <button
        v-else-if="canRetry"
        type="button"
        class="pdf-retry-button"
        :disabled="retrying"
        @click="emit('retry-pdf')"
      >
        <svg v-if="retrying" class="mr-1 h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        {{ retrying ? "Retrying..." : "Missing (Retry)" }}
      </button>
      <span v-else class="pdf-state-label" :class="{ 'bg-surface-accent-muted border-accent-300 text-accent-700': item.pdf_status === 'running' || item.pdf_status === 'queued' }">
        <svg v-if="item.pdf_status === 'running'" class="mr-1 h-3 w-3 animate-spin text-accent-600" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        {{ pdfPendingLabel() }}
      </span>
    </td>
    <td class="whitespace-nowrap">{{ item.year ?? "n/a" }}</td>
    <td class="whitespace-nowrap">{{ item.citation_count }}</td>
    <td>
      <div class="status-badges-row">
        <AppBadge :tone="item.is_new_in_latest_run ? 'info' : 'neutral'">
          {{ item.is_new_in_latest_run ? "New" : "Seen" }}
        </AppBadge>
        <AppBadge :tone="item.is_read ? 'success' : 'warning'">
          {{ item.is_read ? "Read" : "Unread" }}
        </AppBadge>
      </div>
    </td>
    <td class="whitespace-nowrap">{{ formatDate(item.first_seen_at) }}</td>
  </tr>
</template>

<style scoped>
.favorite-star-button {
  @apply inline-flex h-7 w-7 items-center justify-center rounded-full border text-sm leading-none transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset disabled:cursor-not-allowed disabled:opacity-50;
}

.favorite-star-on {
  @apply border-warning-300 bg-warning-100 text-warning-700 hover:bg-warning-200;
}

.favorite-star-off {
  @apply border-stroke-default bg-surface-card-muted text-ink-muted hover:border-stroke-interactive hover:text-ink-secondary;
}

.pdf-link-button {
  @apply inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium border-state-success-border bg-state-success-bg text-state-success-text shadow-sm transition hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset;
}

.pdf-retry-button {
  @apply inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium border-state-warning-border bg-state-warning-bg text-state-warning-text transition hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-focus-offset disabled:cursor-not-allowed disabled:opacity-50;
}

.pdf-state-label {
  @apply inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium border-stroke-default bg-surface-card-muted text-secondary;
}

.status-badges-row {
  @apply inline-flex items-center gap-1 whitespace-nowrap;
}
</style>
