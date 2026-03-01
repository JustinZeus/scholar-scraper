<script setup lang="ts">
import AppButton from "@/components/ui/AppButton.vue";
import AppInput from "@/components/ui/AppInput.vue";
import AppModal from "@/components/ui/AppModal.vue";
import ScholarAvatar from "@/features/scholars/components/ScholarAvatar.vue";
import type { ScholarProfile } from "@/features/scholars";

const props = defineProps<{
  scholar: ScholarProfile | null;
  imageUrlDraft: string;
  imageBusy: boolean;
  imageSaving: boolean;
  imageUploading: boolean;
  saving: boolean;
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "update:image-url-draft", value: string): void;
  (e: "save-image-url"): void;
  (e: "upload-image", event: Event): void;
  (e: "reset-image"): void;
  (e: "toggle"): void;
  (e: "delete"): void;
}>();

function scholarLabel(profile: ScholarProfile): string {
  return profile.display_name || profile.scholar_id;
}

function scholarProfileUrl(scholarId: string): string {
  return `https://scholar.google.com/citations?hl=en&user=${encodeURIComponent(scholarId)}`;
}

function scholarPublicationsRoute(profile: ScholarProfile): { name: string; query: { scholar: string } } {
  return { name: "publications", query: { scholar: String(profile.id) } };
}
</script>

<template>
  <AppModal :open="scholar !== null" title="Scholar settings" @close="emit('close')">
    <div v-if="scholar" class="grid gap-4">
      <div class="flex items-start gap-3">
        <ScholarAvatar
          :label="scholar.display_name"
          :scholar-id="scholar.scholar_id"
          :image-url="scholar.profile_image_url"
        />
        <div class="min-w-0 space-y-1">
          <p class="truncate text-sm font-semibold text-ink-primary">{{ scholarLabel(scholar) }}</p>
          <p class="text-xs text-secondary">ID: <code>{{ scholar.scholar_id }}</code></p>
          <div class="flex flex-wrap items-center gap-3">
            <RouterLink :to="scholarPublicationsRoute(scholar)" class="link-inline text-xs">
              View publications
            </RouterLink>
            <a :href="scholarProfileUrl(scholar.scholar_id)" target="_blank" rel="noreferrer" class="link-inline text-xs">
              Open Google Scholar profile
            </a>
          </div>
        </div>
      </div>

      <div class="grid gap-2">
        <label class="text-sm font-medium text-ink-secondary" :for="`scholar-image-url-${scholar.id}`">
          Profile image URL override
        </label>
        <div class="flex flex-wrap items-center gap-2">
          <div class="min-w-0 flex-1">
            <AppInput
              :id="`scholar-image-url-${scholar.id}`"
              :model-value="imageUrlDraft"
              placeholder="https://example.com/avatar.jpg"
              :disabled="imageBusy"
              @update:model-value="emit('update:image-url-draft', $event as string)"
            />
          </div>
          <AppButton variant="secondary" :disabled="imageBusy" @click="emit('save-image-url')">
            {{ imageSaving ? "Saving..." : "Save URL" }}
          </AppButton>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <label
            :for="`scholar-image-upload-${scholar.id}`"
            class="inline-flex min-h-10 cursor-pointer items-center justify-center rounded-lg border border-stroke-strong bg-action-secondary-bg px-3 py-2 text-sm font-semibold text-action-secondary-text transition hover:bg-action-secondary-hover-bg focus-within:outline-none focus-within:ring-2 focus-within:ring-focus-ring focus-within:ring-offset-2 focus-within:ring-offset-focus-offset"
            :class="{ 'pointer-events-none opacity-60': imageBusy }"
          >
            {{ imageUploading ? "Uploading..." : "Upload image" }}
          </label>
          <input
            :id="`scholar-image-upload-${scholar.id}`"
            type="file"
            class="sr-only"
            accept="image/jpeg,image/png,image/webp,image/gif"
            :disabled="imageBusy"
            @change="emit('upload-image', $event)"
          />
          <AppButton variant="ghost" :disabled="imageBusy" @click="emit('reset-image')">
            Reset image
          </AppButton>
        </div>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-stroke-default pt-3">
        <AppButton variant="secondary" :disabled="imageBusy || saving" @click="emit('toggle')">
          {{ scholar.is_enabled ? "Disable scholar" : "Enable scholar" }}
        </AppButton>
        <AppButton variant="danger" :disabled="imageBusy || saving" @click="emit('delete')">
          Delete scholar
        </AppButton>
      </div>
    </div>
  </AppModal>
</template>
