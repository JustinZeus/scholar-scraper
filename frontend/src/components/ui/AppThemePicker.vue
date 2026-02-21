<script setup lang="ts">
import { computed } from "vue";

import AppButton from "@/components/ui/AppButton.vue";
import AppSelect from "@/components/ui/AppSelect.vue";
import { useThemeStore } from "@/stores/theme";
import type { ThemePresetId } from "@/theme/presets";

const props = withDefaults(
  defineProps<{
    compact?: boolean;
    idPrefix?: string;
  }>(),
  {
    compact: false,
    idPrefix: "theme",
  },
);

const theme = useThemeStore();
const isDarkTheme = computed(() => theme.active === "dark");
const toggleThemeLabel = computed(() =>
  isDarkTheme.value ? "Switch to light theme" : "Switch to dark theme",
);
const selectedPreset = computed<ThemePresetId>({
  get: () => theme.preset,
  set: (value) => theme.setPreset(value),
});
const presetOptions = computed(() => theme.availablePresets);
const themePresetLabel = computed(() => theme.presetLabel);
const selectId = computed(() => `${props.idPrefix}-preset-select`);
const selectWidthClass = computed(() => (props.compact ? "w-32 sm:w-36" : "w-36 sm:w-44"));
const toggleButtonClass = computed(() =>
  props.compact ? "h-9 w-9 rounded-full p-0" : "h-10 w-10 rounded-full p-0",
);

function onToggleTheme(): void {
  theme.setPreference(isDarkTheme.value ? "light" : "dark");
}
</script>

<template>
  <div class="flex items-center justify-end gap-2">
    <div :class="selectWidthClass">
      <label :for="selectId" class="sr-only">Theme preset</label>
      <AppSelect
        :id="selectId"
        v-model="selectedPreset"
        :disabled="presetOptions.length <= 1"
        :title="`Theme preset: ${themePresetLabel}`"
        class="py-1.5"
      >
        <option v-for="preset in presetOptions" :key="preset.id" :value="preset.id">
          {{ preset.label }}
        </option>
      </AppSelect>
    </div>
    <AppButton
      variant="ghost"
      :class="toggleButtonClass"
      :aria-label="toggleThemeLabel"
      :title="toggleThemeLabel"
      @click="onToggleTheme"
    >
      <span class="sr-only">{{ toggleThemeLabel }}</span>
      <svg
        v-if="isDarkTheme"
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        class="h-5 w-5"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="4" />
        <path
          d="M12 2v2.5M12 19.5V22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M2 12h2.5M19.5 12H22M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"
        />
      </svg>
      <svg
        v-else
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        class="h-5 w-5"
        aria-hidden="true"
      >
        <path d="M21 14.5A8.5 8.5 0 1 1 9.5 3 7 7 0 0 0 21 14.5z" />
      </svg>
    </AppButton>
  </div>
</template>
