export const COLOR_SCALE_STEPS = ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"] as const;
export const THEME_MODES = ["light", "dark"] as const;
export const THEME_COLOR_TYPES = ["brand", "info", "success", "warning", "danger"] as const;
export const THEME_SURFACE_KEYS = [
  "app",
  "nav",
  "nav_active",
  "card",
  "card_muted",
  "table",
  "table_header",
  "input",
  "overlay",
] as const;
export const THEME_TEXT_KEYS = ["primary", "secondary", "muted", "inverse", "link"] as const;
export const THEME_BORDER_KEYS = ["default", "strong", "subtle", "interactive"] as const;
export const THEME_FOCUS_KEYS = ["ring", "ring_offset"] as const;
export const THEME_ACTION_VARIANTS = ["primary", "secondary", "ghost", "danger"] as const;
export const THEME_ACTION_KEYS = ["bg", "border", "text", "hover_bg", "hover_border", "hover_text"] as const;
export const THEME_STATE_VARIANTS = ["info", "success", "warning", "danger"] as const;
export const THEME_STATE_KEYS = ["bg", "border", "text"] as const;

export type ColorScaleStep = (typeof COLOR_SCALE_STEPS)[number];
export type ThemeMode = (typeof THEME_MODES)[number];
export type ThemeColorType = (typeof THEME_COLOR_TYPES)[number];
export type ThemeSurfaceKey = (typeof THEME_SURFACE_KEYS)[number];
export type ThemeTextKey = (typeof THEME_TEXT_KEYS)[number];
export type ThemeBorderKey = (typeof THEME_BORDER_KEYS)[number];
export type ThemeFocusKey = (typeof THEME_FOCUS_KEYS)[number];
export type ThemeActionVariant = (typeof THEME_ACTION_VARIANTS)[number];
export type ThemeActionKey = (typeof THEME_ACTION_KEYS)[number];
export type ThemeStateVariant = (typeof THEME_STATE_VARIANTS)[number];
export type ThemeStateKey = (typeof THEME_STATE_KEYS)[number];
export type ThemePresetId = string;

export type ThemeColorScale = Record<ColorScaleStep, string>;
export type ThemeScaleTokenMap = Record<ThemeColorType, ThemeColorScale>;
export type ThemeSurfaceTokens = Record<ThemeSurfaceKey, string>;
export type ThemeTextTokens = Record<ThemeTextKey, string>;
export type ThemeBorderTokens = Record<ThemeBorderKey, string>;
export type ThemeFocusTokens = Record<ThemeFocusKey, string>;
export type ThemeActionTokens = Record<ThemeActionKey, string>;
export type ThemeActionTokenMap = Record<ThemeActionVariant, ThemeActionTokens>;
export type ThemeStateTokens = Record<ThemeStateKey, string>;
export type ThemeStateTokenMap = Record<ThemeStateVariant, ThemeStateTokens>;

export interface ThemePresetOption {
  id: ThemePresetId;
  label: string;
  description: string;
}

export interface ThemeModeDefinition {
  scale: ThemeScaleTokenMap;
  surface: ThemeSurfaceTokens;
  text: ThemeTextTokens;
  border: ThemeBorderTokens;
  focus: ThemeFocusTokens;
  action: ThemeActionTokenMap;
  state: ThemeStateTokenMap;
}

export interface ThemePresetDefinition extends ThemePresetOption {
  modes: Record<ThemeMode, ThemeModeDefinition>;
}

const HEX_COLOR_PATTERN = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
const presetModules = import.meta.glob<{ default?: unknown }>(
  "./presets/*.{json,js}",
  { eager: true },
);

function asObject(value: unknown, path: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Invalid theme schema at ${path}: expected object.`);
  }
  return value as Record<string, unknown>;
}

function asString(value: unknown, path: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`Invalid theme schema at ${path}: expected non-empty string.`);
  }
  return value;
}

function asHexColor(value: unknown, path: string): string {
  const color = asString(value, path).trim();
  if (!HEX_COLOR_PATTERN.test(color)) {
    throw new Error(`Invalid theme color at ${path}: expected #RGB or #RRGGBB.`);
  }
  return color;
}

function readRecordByKeys<K extends readonly string[]>(
  source: unknown,
  keys: K,
  path: string,
): Record<K[number], string> {
  const record = asObject(source, path);
  const result = {} as Record<K[number], string>;

  for (const key of keys as readonly K[number][]) {
    result[key] = asHexColor(record[key], `${path}.${key}`);
  }

  return result;
}

function readScaleTokens(source: unknown, path: string): ThemeScaleTokenMap {
  const record = asObject(source, path);
  return {
    brand: readRecordByKeys(record.brand, COLOR_SCALE_STEPS, `${path}.brand`),
    info: readRecordByKeys(record.info, COLOR_SCALE_STEPS, `${path}.info`),
    success: readRecordByKeys(record.success, COLOR_SCALE_STEPS, `${path}.success`),
    warning: readRecordByKeys(record.warning, COLOR_SCALE_STEPS, `${path}.warning`),
    danger: readRecordByKeys(record.danger, COLOR_SCALE_STEPS, `${path}.danger`),
  };
}

function readActionTokens(source: unknown, path: string): ThemeActionTokenMap {
  const record = asObject(source, path);
  return {
    primary: readRecordByKeys(record.primary, THEME_ACTION_KEYS, `${path}.primary`),
    secondary: readRecordByKeys(record.secondary, THEME_ACTION_KEYS, `${path}.secondary`),
    ghost: readRecordByKeys(record.ghost, THEME_ACTION_KEYS, `${path}.ghost`),
    danger: readRecordByKeys(record.danger, THEME_ACTION_KEYS, `${path}.danger`),
  };
}

function readStateTokens(source: unknown, path: string): ThemeStateTokenMap {
  const record = asObject(source, path);
  return {
    info: readRecordByKeys(record.info, THEME_STATE_KEYS, `${path}.info`),
    success: readRecordByKeys(record.success, THEME_STATE_KEYS, `${path}.success`),
    warning: readRecordByKeys(record.warning, THEME_STATE_KEYS, `${path}.warning`),
    danger: readRecordByKeys(record.danger, THEME_STATE_KEYS, `${path}.danger`),
  };
}

function readModeTokens(source: unknown, path: string): ThemeModeDefinition {
  const record = asObject(source, path);
  return {
    scale: readScaleTokens(record.scale, `${path}.scale`),
    surface: readRecordByKeys(record.surface, THEME_SURFACE_KEYS, `${path}.surface`),
    text: readRecordByKeys(record.text, THEME_TEXT_KEYS, `${path}.text`),
    border: readRecordByKeys(record.border, THEME_BORDER_KEYS, `${path}.border`),
    focus: readRecordByKeys(record.focus, THEME_FOCUS_KEYS, `${path}.focus`),
    action: readActionTokens(record.action, `${path}.action`),
    state: readStateTokens(record.state, `${path}.state`),
  };
}

function validateThemePreset(source: unknown, sourcePath: string): ThemePresetDefinition {
  const record = asObject(source, sourcePath);
  const id = asString(record.id, `${sourcePath}.id`);

  return {
    id,
    label: asString(record.label, `${sourcePath}.label`),
    description: asString(record.description, `${sourcePath}.description`),
    modes: {
      light: readModeTokens(asObject(record.modes, `${sourcePath}.modes`).light, `${sourcePath}.modes.light`),
      dark: readModeTokens(asObject(record.modes, `${sourcePath}.modes`).dark, `${sourcePath}.modes.dark`),
    },
  };
}

const loadedPresetSources = Object.entries(presetModules)
  .sort(([left], [right]) => left.localeCompare(right))
  .map(([sourcePath, moduleValue]) => ({
    sourcePath,
    source:
      moduleValue && typeof moduleValue === "object" && "default" in moduleValue
        ? moduleValue.default
        : moduleValue,
  }));

export const THEME_PRESETS: ThemePresetDefinition[] = loadedPresetSources.map(
  ({ source, sourcePath }) => validateThemePreset(source, sourcePath),
);

const presetById = new Map<ThemePresetId, ThemePresetDefinition>();
for (const preset of THEME_PRESETS) {
  if (presetById.has(preset.id)) {
    throw new Error(`Duplicate theme preset id detected: ${preset.id}`);
  }
  presetById.set(preset.id, preset);
}

export const DEFAULT_THEME_PRESET: ThemePresetId = presetById.has("parchment")
  ? "parchment"
  : (THEME_PRESETS[0]?.id ?? "parchment");

export const THEME_PRESET_OPTIONS: ThemePresetOption[] = THEME_PRESETS.map((preset) => ({
  id: preset.id,
  label: preset.label,
  description: preset.description,
}));

function normalizeHex(hex: string): string {
  const normalized = hex.trim().replace(/^#/, "");
  if (normalized.length === 3) {
    return normalized
      .split("")
      .map((char) => `${char}${char}`)
      .join("");
  }
  return normalized;
}

function hexToRgbTriplet(hex: string): string {
  const normalized = normalizeHex(hex);
  const red = parseInt(normalized.slice(0, 2), 16);
  const green = parseInt(normalized.slice(2, 4), 16);
  const blue = parseInt(normalized.slice(4, 6), 16);
  return `${red} ${green} ${blue}`;
}

export function isThemePresetId(value: string): boolean {
  return presetById.has(value);
}

export function getThemePreset(presetId: ThemePresetId): ThemePresetDefinition {
  return presetById.get(presetId) ?? presetById.get(DEFAULT_THEME_PRESET) ?? THEME_PRESETS[0];
}

export function themeCssVariables(presetId: ThemePresetId, mode: ThemeMode): Record<string, string> {
  const preset = getThemePreset(presetId);
  const selected = preset.modes[mode];
  const entries: Array<[string, string]> = [];

  for (const role of THEME_COLOR_TYPES) {
    for (const step of COLOR_SCALE_STEPS) {
      entries.push([`--color-${role}-${step}`, hexToRgbTriplet(selected.scale[role][step])]);
    }
  }

  for (const key of THEME_SURFACE_KEYS) {
    entries.push([`--theme-surface-${key.replace(/_/g, "-")}`, hexToRgbTriplet(selected.surface[key])]);
  }

  for (const key of THEME_TEXT_KEYS) {
    entries.push([`--theme-text-${key.replace(/_/g, "-")}`, hexToRgbTriplet(selected.text[key])]);
  }

  for (const key of THEME_BORDER_KEYS) {
    entries.push([`--theme-border-${key.replace(/_/g, "-")}`, hexToRgbTriplet(selected.border[key])]);
  }

  for (const key of THEME_FOCUS_KEYS) {
    entries.push([`--theme-focus-${key.replace(/_/g, "-")}`, hexToRgbTriplet(selected.focus[key])]);
  }

  for (const variant of THEME_ACTION_VARIANTS) {
    for (const key of THEME_ACTION_KEYS) {
      entries.push([
        `--theme-action-${variant}-${key.replace(/_/g, "-")}`,
        hexToRgbTriplet(selected.action[variant][key]),
      ]);
    }
  }

  for (const variant of THEME_STATE_VARIANTS) {
    for (const key of THEME_STATE_KEYS) {
      entries.push([
        `--theme-state-${variant}-${key.replace(/_/g, "-")}`,
        hexToRgbTriplet(selected.state[variant][key]),
      ]);
    }
  }

  return Object.fromEntries(entries);
}
