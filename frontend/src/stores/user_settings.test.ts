import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { useUserSettingsStore } from "@/stores/user_settings";

describe("user settings store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("falls back network failure threshold to 2 when policy value is missing", () => {
    const store = useUserSettingsStore();

    store.applySettings({
      auto_run_enabled: true,
      run_interval_minutes: 60,
      request_delay_seconds: 2,
      nav_visible_pages: ["dashboard", "scholars", "settings"],
      policy: {
        min_run_interval_minutes: 15,
        min_request_delay_seconds: 2,
        automation_allowed: true,
        manual_run_allowed: true,
        blocked_failure_threshold: 1,
        network_failure_threshold: Number.NaN,
        cooldown_blocked_seconds: 1800,
        cooldown_network_seconds: 900,
      },
      safety_state: {
        cooldown_active: false,
        cooldown_reason: null,
        cooldown_reason_label: null,
        cooldown_until: null,
        cooldown_remaining_seconds: 0,
        recommended_action: null,
        counters: {
          consecutive_blocked_runs: 0,
          consecutive_network_runs: 0,
          cooldown_entry_count: 0,
          blocked_start_count: 0,
          last_blocked_failure_count: 0,
          last_network_failure_count: 0,
          last_evaluated_run_id: null,
        },
      },
    });

    expect(store.networkFailureThreshold).toBe(2);
  });
});
