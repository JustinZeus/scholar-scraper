// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import ScrapeSafetyBadge from "./ScrapeSafetyBadge.vue";
import { createDefaultSafetyState, type ScrapeSafetyState } from "@/features/safety";

function buildState(overrides: Partial<ScrapeSafetyState> = {}): ScrapeSafetyState {
  return { ...createDefaultSafetyState(), ...overrides };
}

describe("ScrapeSafetyBadge", () => {
  it("shows ready tooltip when cooldown is inactive", () => {
    const wrapper = mount(ScrapeSafetyBadge, {
      props: { state: buildState({ cooldown_active: false }) },
    });
    expect(wrapper.text()).toContain("Safety ready");
    const hint = wrapper.findComponent({ name: "AppHelpHint" });
    expect(hint.exists()).toBe(true);
    expect(hint.props("text")).toContain("No active cooldown");
  });

  it("shows cooldown tooltip with reason and action when active", () => {
    const wrapper = mount(ScrapeSafetyBadge, {
      props: {
        state: buildState({
          cooldown_active: true,
          cooldown_reason: "blocked_failure_threshold_exceeded",
          cooldown_reason_label: "Too many blocked requests",
          recommended_action: "Wait for cooldown to expire",
          cooldown_remaining_seconds: 120,
        }),
      },
    });
    expect(wrapper.text()).toContain("Safety cooldown");
    const hint = wrapper.findComponent({ name: "AppHelpHint" });
    expect(hint.exists()).toBe(true);
    const text = hint.props("text") as string;
    expect(text).toContain("Google Scholar rate-limits");
    expect(text).toContain("Too many blocked requests");
    expect(text).toContain("Wait for cooldown to expire");
  });

  it("shows cooldown tooltip without optional fields", () => {
    const wrapper = mount(ScrapeSafetyBadge, {
      props: {
        state: buildState({
          cooldown_active: true,
          cooldown_reason: "some_reason",
          cooldown_reason_label: null,
          recommended_action: null,
          cooldown_remaining_seconds: 60,
        }),
      },
    });
    const hint = wrapper.findComponent({ name: "AppHelpHint" });
    const text = hint.props("text") as string;
    expect(text).toContain("Google Scholar rate-limits");
    expect(text).not.toContain("Why:");
    expect(text).not.toContain("Action:");
  });
});
