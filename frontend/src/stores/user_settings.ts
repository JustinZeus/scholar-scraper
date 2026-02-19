import { defineStore } from "pinia";

import { fetchSettings, type UserSettings } from "@/features/settings";
import { createDefaultSafetyState, normalizeSafetyState, type ScrapeSafetyState } from "@/features/safety";

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
    minRunIntervalMinutes: 15,
    minRequestDelaySeconds: 2,
    automationAllowed: true,
    manualRunAllowed: true,
    blockedFailureThreshold: 1,
    networkFailureThreshold: 2,
    cooldownBlockedSeconds: 1800,
    cooldownNetworkSeconds: 900,
    safetyState: createDefaultSafetyState() as ScrapeSafetyState,
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
      this.minRunIntervalMinutes = Number.isFinite(settings.policy?.min_run_interval_minutes)
        ? Math.max(15, settings.policy.min_run_interval_minutes)
        : 15;
      this.minRequestDelaySeconds = Number.isFinite(settings.policy?.min_request_delay_seconds)
        ? Math.max(2, settings.policy.min_request_delay_seconds)
        : 2;
      this.automationAllowed = Boolean(settings.policy?.automation_allowed ?? true);
      this.manualRunAllowed = Boolean(settings.policy?.manual_run_allowed ?? true);
      this.blockedFailureThreshold = Number.isFinite(settings.policy?.blocked_failure_threshold)
        ? Math.max(1, settings.policy.blocked_failure_threshold)
        : 1;
      this.networkFailureThreshold = Number.isFinite(settings.policy?.network_failure_threshold)
        ? Math.max(1, settings.policy.network_failure_threshold)
        : 1;
      this.cooldownBlockedSeconds = Number.isFinite(settings.policy?.cooldown_blocked_seconds)
        ? Math.max(60, settings.policy.cooldown_blocked_seconds)
        : 1800;
      this.cooldownNetworkSeconds = Number.isFinite(settings.policy?.cooldown_network_seconds)
        ? Math.max(60, settings.policy.cooldown_network_seconds)
        : 900;
      this.safetyState = normalizeSafetyState(settings.safety_state);
    },
    reset(): void {
      this.navVisiblePages = [...DEFAULT_NAV_VISIBLE_PAGES];
      this.minRunIntervalMinutes = 15;
      this.minRequestDelaySeconds = 2;
      this.automationAllowed = true;
      this.manualRunAllowed = true;
      this.blockedFailureThreshold = 1;
      this.networkFailureThreshold = 2;
      this.cooldownBlockedSeconds = 1800;
      this.cooldownNetworkSeconds = 900;
      this.safetyState = createDefaultSafetyState();
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
