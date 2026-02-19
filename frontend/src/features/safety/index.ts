export interface ScrapeSafetyCounters {
  consecutive_blocked_runs: number;
  consecutive_network_runs: number;
  cooldown_entry_count: number;
  blocked_start_count: number;
  last_blocked_failure_count: number;
  last_network_failure_count: number;
  last_evaluated_run_id: number | null;
}

export interface ScrapeSafetyState {
  cooldown_active: boolean;
  cooldown_reason: string | null;
  cooldown_reason_label: string | null;
  cooldown_until: string | null;
  cooldown_remaining_seconds: number;
  recommended_action: string | null;
  counters: ScrapeSafetyCounters;
}

export function createDefaultSafetyCounters(): ScrapeSafetyCounters {
  return {
    consecutive_blocked_runs: 0,
    consecutive_network_runs: 0,
    cooldown_entry_count: 0,
    blocked_start_count: 0,
    last_blocked_failure_count: 0,
    last_network_failure_count: 0,
    last_evaluated_run_id: null,
  };
}

export function createDefaultSafetyState(): ScrapeSafetyState {
  return {
    cooldown_active: false,
    cooldown_reason: null,
    cooldown_reason_label: null,
    cooldown_until: null,
    cooldown_remaining_seconds: 0,
    recommended_action: null,
    counters: createDefaultSafetyCounters(),
  };
}

function parseNumber(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return fallback;
}

function parseNullableString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

export function normalizeSafetyState(value: unknown): ScrapeSafetyState {
  if (!value || typeof value !== "object") {
    return createDefaultSafetyState();
  }

  const raw = value as Record<string, unknown>;
  const rawCounters = raw.counters;
  const counters = rawCounters && typeof rawCounters === "object"
    ? (rawCounters as Record<string, unknown>)
    : {};

  return {
    cooldown_active: Boolean(raw.cooldown_active),
    cooldown_reason: parseNullableString(raw.cooldown_reason),
    cooldown_reason_label: parseNullableString(raw.cooldown_reason_label),
    cooldown_until: parseNullableString(raw.cooldown_until),
    cooldown_remaining_seconds: Math.max(0, parseNumber(raw.cooldown_remaining_seconds, 0)),
    recommended_action: parseNullableString(raw.recommended_action),
    counters: {
      consecutive_blocked_runs: Math.max(0, parseNumber(counters.consecutive_blocked_runs, 0)),
      consecutive_network_runs: Math.max(0, parseNumber(counters.consecutive_network_runs, 0)),
      cooldown_entry_count: Math.max(0, parseNumber(counters.cooldown_entry_count, 0)),
      blocked_start_count: Math.max(0, parseNumber(counters.blocked_start_count, 0)),
      last_blocked_failure_count: Math.max(0, parseNumber(counters.last_blocked_failure_count, 0)),
      last_network_failure_count: Math.max(0, parseNumber(counters.last_network_failure_count, 0)),
      last_evaluated_run_id:
        counters.last_evaluated_run_id === null
          ? null
          : Math.max(0, parseNumber(counters.last_evaluated_run_id, 0)),
    },
  };
}

export function formatCooldownCountdown(seconds: number): string {
  const bounded = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  if (bounded <= 0) {
    return "0s";
  }

  const hours = Math.floor(bounded / 3600);
  const minutes = Math.floor((bounded % 3600) / 60);
  const secs = bounded % 60;

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${secs}s`;
  }
  return `${secs}s`;
}
