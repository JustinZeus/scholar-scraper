import { defineStore } from "pinia";

import { fetchSettings, type UserSettings } from "@/features/settings";

export const REQUIRED_NAV_PAGES = ["dashboard", "scholars", "settings"] as const;
export const DEFAULT_NAV_VISIBLE_PAGES = [
  "dashboard",
  "scholars",
  "publications",
  "settings",
  "style-guide",
  "runs",
  "users",
] as const;

const ALLOWED_NAV_PAGES = new Set<string>(DEFAULT_NAV_VISIBLE_PAGES);
const REQUIRED_NAV_PAGES_SET = new Set<string>(REQUIRED_NAV_PAGES);

function normalizeNavVisiblePages(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [...DEFAULT_NAV_VISIBLE_PAGES];
  }

  const deduped: string[] = [];
  const seen = new Set<string>();

  for (const candidate of value) {
    if (typeof candidate !== "string") {
      continue;
    }

    const pageId = candidate.trim();
    if (!ALLOWED_NAV_PAGES.has(pageId) || seen.has(pageId)) {
      continue;
    }

    seen.add(pageId);
    deduped.push(pageId);
  }

  for (const requiredPage of REQUIRED_NAV_PAGES) {
    if (!seen.has(requiredPage)) {
      deduped.push(requiredPage);
      seen.add(requiredPage);
    }
  }

  return deduped;
}

export const useUserSettingsStore = defineStore("userSettings", {
  state: () => ({
    navVisiblePages: [...DEFAULT_NAV_VISIBLE_PAGES] as string[],
  }),
  getters: {
    visiblePageSet: (state) => new Set(state.navVisiblePages),
  },
  actions: {
    setNavVisiblePages(value: unknown): void {
      this.navVisiblePages = normalizeNavVisiblePages(value);
    },
    applySettings(settings: UserSettings): void {
      this.setNavVisiblePages(settings.nav_visible_pages);
    },
    reset(): void {
      this.navVisiblePages = [...DEFAULT_NAV_VISIBLE_PAGES];
    },
    isPageVisible(pageId: string): boolean {
      if (REQUIRED_NAV_PAGES_SET.has(pageId)) {
        return true;
      }
      return this.visiblePageSet.has(pageId);
    },
    async bootstrap(): Promise<void> {
      try {
        const settings = await fetchSettings();
        this.applySettings(settings);
      } catch {
        this.reset();
      }
    },
  },
});

export function normalizeUserNavVisiblePages(value: unknown): string[] {
  return normalizeNavVisiblePages(value);
}
