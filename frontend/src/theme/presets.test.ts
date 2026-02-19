import { describe, expect, it } from "vitest";

import {
  COLOR_SCALE_STEPS,
  THEME_ACTION_KEYS,
  THEME_ACTION_VARIANTS,
  THEME_BORDER_KEYS,
  THEME_COLOR_TYPES,
  THEME_FOCUS_KEYS,
  THEME_PRESETS,
  THEME_STATE_KEYS,
  THEME_STATE_VARIANTS,
  THEME_SURFACE_KEYS,
  THEME_TEXT_KEYS,
  THEME_MODES,
  themeCssVariables,
} from "@/theme/presets";

const RGB_TRIPLET_PATTERN = /^\d{1,3} \d{1,3} \d{1,3}$/;

describe("theme presets", () => {
  it("exposes unique preset identifiers", () => {
    const ids = THEME_PRESETS.map((preset) => preset.id);
    expect(ids.length).toBeGreaterThan(0);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("builds complete CSS variable maps for each preset and mode", () => {
    const expectedCount =
      THEME_COLOR_TYPES.length * COLOR_SCALE_STEPS.length +
      THEME_SURFACE_KEYS.length +
      THEME_TEXT_KEYS.length +
      THEME_BORDER_KEYS.length +
      THEME_FOCUS_KEYS.length +
      THEME_ACTION_VARIANTS.length * THEME_ACTION_KEYS.length +
      THEME_STATE_VARIANTS.length * THEME_STATE_KEYS.length;

    for (const preset of THEME_PRESETS) {
      for (const mode of THEME_MODES) {
        const cssVars = themeCssVariables(preset.id, mode);
        expect(Object.keys(cssVars)).toHaveLength(expectedCount);
        expect(cssVars["--theme-surface-app"]).toBeDefined();
        expect(cssVars["--theme-text-primary"]).toBeDefined();
        expect(cssVars["--theme-border-default"]).toBeDefined();
        expect(cssVars["--theme-focus-ring"]).toBeDefined();
        expect(cssVars["--theme-action-primary-bg"]).toBeDefined();
        expect(cssVars["--theme-state-warning-text"]).toBeDefined();
      }
    }
  });

  it("converts all theme variables to RGB triplets", () => {
    for (const preset of THEME_PRESETS) {
      for (const mode of THEME_MODES) {
        const cssVars = themeCssVariables(preset.id, mode);
        for (const value of Object.values(cssVars)) {
          expect(value).toMatch(RGB_TRIPLET_PATTERN);
          const [red, green, blue] = value.split(" ").map(Number);
          expect(red).toBeGreaterThanOrEqual(0);
          expect(red).toBeLessThanOrEqual(255);
          expect(green).toBeGreaterThanOrEqual(0);
          expect(green).toBeLessThanOrEqual(255);
          expect(blue).toBeGreaterThanOrEqual(0);
          expect(blue).toBeLessThanOrEqual(255);
        }
      }
    }
  });
});
