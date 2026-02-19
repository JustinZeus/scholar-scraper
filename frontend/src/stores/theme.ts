import { defineStore } from "pinia";
import {
  DEFAULT_THEME_PRESET,
  THEME_PRESET_OPTIONS,
  getThemePreset,
  isThemePresetId,
  themeCssVariables,
  type ThemePresetId,
} from "@/theme/presets";

export type ThemePreference = "system" | "light" | "dark";
export type ThemeValue = "light" | "dark";

const STORAGE_KEY = "scholarr-theme-preference";
const PRESET_STORAGE_KEY = "scholarr-theme-preset";

function systemTheme(): ThemeValue {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme: ThemeValue, preference: ThemePreference, preset: ThemePresetId): void {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.setAttribute("data-theme-preference", preference);
  root.setAttribute("data-theme-preset", preset);

  const variables = themeCssVariables(preset, theme);
  Object.entries(variables).forEach(([name, value]) => {
    root.style.setProperty(name, value);
  });
}

export const useThemeStore = defineStore("theme", {
  state: () => ({
    preference: "system" as ThemePreference,
    active: "light" as ThemeValue,
    preset: DEFAULT_THEME_PRESET as ThemePresetId,
  }),
  getters: {
    availablePresets: () => THEME_PRESET_OPTIONS,
    presetLabel: (state) => getThemePreset(state.preset).label,
  },
  actions: {
    initialize(): void {
      let storedPreference: string | null = null;
      let storedPreset: string | null = null;
      try {
        storedPreference = localStorage.getItem(STORAGE_KEY);
        storedPreset = localStorage.getItem(PRESET_STORAGE_KEY);
      } catch (_err) {
        storedPreference = null;
        storedPreset = null;
      }

      if (storedPreference === "light" || storedPreference === "dark" || storedPreference === "system") {
        this.preference = storedPreference;
      }

      if (storedPreset && isThemePresetId(storedPreset)) {
        this.preset = storedPreset;
      }

      this.active = this.preference === "system" ? systemTheme() : this.preference;
      applyTheme(this.active, this.preference, this.preset);

      const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
      const handleSystemChange = (): void => {
        if (this.preference !== "system") {
          return;
        }
        this.active = systemTheme();
        applyTheme(this.active, this.preference, this.preset);
      };

      if (typeof mediaQuery.addEventListener === "function") {
        mediaQuery.addEventListener("change", handleSystemChange);
      } else if (typeof mediaQuery.addListener === "function") {
        mediaQuery.addListener(handleSystemChange);
      }
    },
    setPreference(preference: ThemePreference): void {
      this.preference = preference;
      this.active = preference === "system" ? systemTheme() : preference;
      applyTheme(this.active, this.preference, this.preset);

      try {
        localStorage.setItem(STORAGE_KEY, preference);
      } catch (_err) {
        // Ignore storage failures in private contexts.
      }
    },
    setPreset(preset: ThemePresetId): void {
      if (!isThemePresetId(preset)) {
        return;
      }

      this.preset = preset;
      applyTheme(this.active, this.preference, this.preset);

      try {
        localStorage.setItem(PRESET_STORAGE_KEY, preset);
      } catch (_err) {
        // Ignore storage failures in private contexts.
      }
    },
  },
});
