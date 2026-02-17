import { defineStore } from "pinia";

export type ThemePreference = "system" | "light" | "dark";
export type ThemeValue = "light" | "dark";

const STORAGE_KEY = "scholarr-theme-preference";

function systemTheme(): ThemeValue {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme: ThemeValue, preference: ThemePreference): void {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.setAttribute("data-theme-preference", preference);
}

export const useThemeStore = defineStore("theme", {
  state: () => ({
    preference: "system" as ThemePreference,
    active: "light" as ThemeValue,
  }),
  actions: {
    initialize(): void {
      let stored: string | null = null;
      try {
        stored = localStorage.getItem(STORAGE_KEY);
      } catch (_err) {
        stored = null;
      }

      if (stored === "light" || stored === "dark" || stored === "system") {
        this.preference = stored;
      }

      this.active = this.preference === "system" ? systemTheme() : this.preference;
      applyTheme(this.active, this.preference);
    },
    setPreference(preference: ThemePreference): void {
      this.preference = preference;
      this.active = preference === "system" ? systemTheme() : preference;
      applyTheme(this.active, this.preference);

      try {
        localStorage.setItem(STORAGE_KEY, preference);
      } catch (_err) {
        // Ignore storage failures in private contexts.
      }
    },
  },
});
