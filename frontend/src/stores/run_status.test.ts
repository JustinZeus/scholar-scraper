import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { ApiRequestError } from "@/lib/api/errors";
import { createDefaultSafetyState } from "@/features/safety";

vi.mock("@/features/runs", () => ({
  listRuns: vi.fn(),
  triggerManualRun: vi.fn(),
}));

import { listRuns, triggerManualRun } from "@/features/runs";
import {
  RUN_STATUS_POLL_INTERVAL_MS,
  RUN_STATUS_STARTING_PHASE_MS,
  useRunStatusStore,
} from "@/stores/run_status";

function buildRun(overrides: Partial<{
  id: number;
  trigger_type: string;
  status: string;
  start_dt: string;
  end_dt: string | null;
  scholar_count: number;
  new_publication_count: number;
  failed_count: number;
  partial_count: number;
}> = {}) {
  return {
    id: 1,
    trigger_type: "manual",
    status: "success",
    start_dt: "2026-02-19T12:00:00Z",
    end_dt: "2026-02-19T12:01:00Z",
    scholar_count: 3,
    new_publication_count: 2,
    failed_count: 0,
    partial_count: 0,
    ...overrides,
  };
}

function buildRunsPayload(runs: ReturnType<typeof buildRun>[]) {
  return {
    runs,
    safety_state: createDefaultSafetyState(),
  };
}

describe("run status store", () => {
  const mockedListRuns = vi.mocked(listRuns);
  const mockedTriggerManualRun = vi.mocked(triggerManualRun);

  beforeEach(() => {
    setActivePinia(createPinia());
    mockedListRuns.mockReset();
    mockedTriggerManualRun.mockReset();
    vi.useRealTimers();
  });

  afterEach(() => {
    useRunStatusStore().reset();
    vi.useRealTimers();
  });

  it("bootstraps from latest run and exposes idle start state", async () => {
    mockedListRuns.mockResolvedValueOnce(buildRunsPayload([buildRun({ id: 11, status: "success" })]));

    const store = useRunStatusStore();
    await store.bootstrap();

    expect(mockedListRuns).toHaveBeenCalledWith({ limit: 1 });
    expect(store.latestRun?.id).toBe(11);
    expect(store.canStart).toBe(true);
    expect(store.isRunActive).toBe(false);
    expect(store.isPolling).toBe(false);
  });

  it("starts manual checks and marks active state", async () => {
    mockedTriggerManualRun.mockResolvedValueOnce({
      run_id: 25,
      status: "running",
      scholar_count: 0,
      succeeded_count: 0,
      failed_count: 0,
      partial_count: 0,
      new_publication_count: 0,
      reused_existing_run: false,
      idempotency_key: "abc",
      safety_state: createDefaultSafetyState(),
    });
    mockedListRuns.mockResolvedValueOnce(
      buildRunsPayload([buildRun({ id: 25, status: "running", end_dt: null })]),
    );

    const store = useRunStatusStore();
    const result = await store.startManualCheck();

    expect(result).toEqual({
      kind: "started",
      runId: 25,
      reusedExistingRun: false,
    });
    expect(store.latestRun?.id).toBe(25);
    expect(store.isRunActive).toBe(true);
    expect(store.isPolling).toBe(true);
  });

  it("normalizes run_in_progress responses into already_running state", async () => {
    mockedTriggerManualRun.mockRejectedValueOnce(
      new ApiRequestError({
        status: 409,
        code: "run_in_progress",
        message: "A run is already in progress for this account.",
        details: { run_id: 42 },
        requestId: "req_123",
      }),
    );
    mockedListRuns.mockResolvedValueOnce(
      buildRunsPayload([buildRun({ id: 42, status: "running", end_dt: null })]),
    );

    const store = useRunStatusStore();
    const result = await store.startManualCheck();

    expect(result).toEqual({
      kind: "already_running",
      runId: 42,
      requestId: "req_123",
    });
    expect(store.latestRun?.id).toBe(42);
    expect(store.isRunActive).toBe(true);
    expect(store.lastErrorMessage).toBeNull();
  });

  it("polls while a run is active and stops when it completes", async () => {
    vi.useFakeTimers();
    mockedListRuns
      .mockResolvedValueOnce(buildRunsPayload([buildRun({ id: 90, status: "running", end_dt: null })]))
      .mockResolvedValueOnce(buildRunsPayload([buildRun({ id: 90, status: "success" })]));

    const store = useRunStatusStore();
    await store.syncLatest();
    expect(store.isPolling).toBe(true);

    await vi.advanceTimersByTimeAsync(RUN_STATUS_POLL_INTERVAL_MS + 10);

    expect(mockedListRuns).toHaveBeenCalledTimes(2);
    expect(store.latestRun?.status).toBe("success");
    expect(store.isPolling).toBe(false);
    expect(store.isRunActive).toBe(false);
  });

  it("stores cooldown safety state when manual start is blocked by policy cooldown", async () => {
    mockedTriggerManualRun.mockRejectedValueOnce(
      new ApiRequestError({
        status: 429,
        code: "scrape_cooldown_active",
        message: "Scrape safety cooldown is active; run start is temporarily blocked.",
        details: {
          safety_state: {
            cooldown_active: true,
            cooldown_reason: "blocked_failure_threshold_exceeded",
            cooldown_reason_label: "Blocked responses exceeded safety threshold",
            cooldown_until: "2026-02-19T12:30:00Z",
            cooldown_remaining_seconds: 600,
            recommended_action: "Wait for cooldown to expire.",
            counters: {
              consecutive_blocked_runs: 1,
              consecutive_network_runs: 0,
              cooldown_entry_count: 1,
              blocked_start_count: 2,
              last_blocked_failure_count: 1,
              last_network_failure_count: 0,
              last_evaluated_run_id: 10,
            },
          },
        },
      }),
    );

    const store = useRunStatusStore();
    const result = await store.startManualCheck();

    expect(result.kind).toBe("error");
    expect(store.safetyState.cooldown_active).toBe(true);
    expect(store.canStart).toBe(false);
  });

  it("switches from starting to in-progress when trigger request remains open", async () => {
    vi.useFakeTimers();
    mockedTriggerManualRun.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(() => {
            resolve({
              run_id: 77,
              status: "running",
              scholar_count: 0,
              succeeded_count: 0,
              failed_count: 0,
              partial_count: 0,
              new_publication_count: 0,
              reused_existing_run: false,
              idempotency_key: "x",
              safety_state: createDefaultSafetyState(),
            });
          }, RUN_STATUS_STARTING_PHASE_MS + 500);
        }),
    );
    mockedListRuns.mockResolvedValueOnce(buildRunsPayload([]));

    const store = useRunStatusStore();
    const startPromise = store.startManualCheck();

    expect(store.isSubmitting).toBe(true);
    expect(store.isLikelyRunning).toBe(false);

    await vi.advanceTimersByTimeAsync(RUN_STATUS_STARTING_PHASE_MS + 20);
    expect(store.isLikelyRunning).toBe(true);
    await vi.advanceTimersByTimeAsync(520);
    await startPromise;
    expect(store.isRunActive).toBe(true);
  });
});
