import { defineStore } from "pinia";

import { listRuns, triggerManualRun, type RunListItem } from "@/features/runs";
import { ApiRequestError } from "@/lib/api/errors";

export const RUN_STATUS_POLL_INTERVAL_MS = 5000;
export const RUN_STATUS_STARTING_PHASE_MS = 1500;

export type StartManualCheckResult =
  | {
      kind: "started";
      runId: number;
      reusedExistingRun: boolean;
    }
  | {
      kind: "already_running";
      runId: number | null;
      requestId: string | null;
    }
  | {
      kind: "error";
      message: string;
      requestId: string | null;
    };

let pollTimer: ReturnType<typeof setInterval> | null = null;
let syncPromise: Promise<void> | null = null;
let submittingPhaseTimer: ReturnType<typeof setTimeout> | null = null;

function parseRunId(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number.parseInt(value, 10);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function extractRunIdFromDetails(details: unknown): number | null {
  if (!details || typeof details !== "object") {
    return null;
  }

  const runIdCandidate = (details as Record<string, unknown>).run_id;
  return parseRunId(runIdCandidate);
}

function buildPlaceholderRunningRun(runId: number): RunListItem {
  return {
    id: runId,
    trigger_type: "manual",
    status: "running",
    start_dt: new Date().toISOString(),
    end_dt: null,
    scholar_count: 0,
    new_publication_count: 0,
    failed_count: 0,
    partial_count: 0,
  };
}

export const useRunStatusStore = defineStore("runStatus", {
  state: () => ({
    latestRun: null as RunListItem | null,
    isSubmitting: false,
    assumeRunningFromSubmission: false,
    isPolling: false,
    lastErrorMessage: null as string | null,
    lastErrorRequestId: null as string | null,
    lastSyncAt: null as number | null,
  }),
  getters: {
    isRunActive(state): boolean {
      return state.isSubmitting || state.latestRun?.status === "running";
    },
    isLikelyRunning(state): boolean {
      return state.latestRun?.status === "running" || state.assumeRunningFromSubmission;
    },
    canStart(): boolean {
      return !this.isRunActive;
    },
  },
  actions: {
    clearSubmittingPhaseTimer(): void {
      if (submittingPhaseTimer !== null) {
        clearTimeout(submittingPhaseTimer);
        submittingPhaseTimer = null;
      }
    },
    beginSubmittingPhaseTracking(): void {
      this.assumeRunningFromSubmission = false;
      this.clearSubmittingPhaseTimer();
      submittingPhaseTimer = setTimeout(() => {
        if (!this.isSubmitting) {
          return;
        }
        this.assumeRunningFromSubmission = true;
      }, RUN_STATUS_STARTING_PHASE_MS);
    },
    setLatestRun(run: RunListItem | null): void {
      this.latestRun = run;
      this.lastSyncAt = Date.now();
      this.lastErrorMessage = null;
      this.lastErrorRequestId = null;
      if (run?.status === "running") {
        this.assumeRunningFromSubmission = true;
      } else if (!this.isSubmitting) {
        this.assumeRunningFromSubmission = false;
      }
      this.updatePolling();
    },
    startPolling(): void {
      if (pollTimer !== null) {
        this.isPolling = true;
        return;
      }

      this.isPolling = true;
      pollTimer = setInterval(() => {
        void this.syncLatest();
      }, RUN_STATUS_POLL_INTERVAL_MS);
    },
    stopPolling(): void {
      if (pollTimer !== null) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
      this.isPolling = false;
    },
    updatePolling(): void {
      if (this.isRunActive) {
        this.startPolling();
        return;
      }
      this.stopPolling();
    },
    async syncLatest(): Promise<void> {
      if (syncPromise) {
        await syncPromise;
        return;
      }

      syncPromise = (async () => {
        try {
          const runs = await listRuns({ limit: 1 });
          const latest = runs[0] ?? null;
          this.latestRun = latest;
          this.lastSyncAt = Date.now();
          this.lastErrorMessage = null;
          this.lastErrorRequestId = null;
          if (latest?.status === "running") {
            this.assumeRunningFromSubmission = true;
          } else if (!this.isSubmitting) {
            this.assumeRunningFromSubmission = false;
          }
        } catch (error) {
          if (error instanceof ApiRequestError) {
            this.lastErrorMessage = error.message;
            this.lastErrorRequestId = error.requestId;
          } else {
            this.lastErrorMessage = "Unable to refresh check status.";
            this.lastErrorRequestId = null;
          }
        } finally {
          syncPromise = null;
          this.updatePolling();
        }
      })();

      await syncPromise;
    },
    async bootstrap(): Promise<void> {
      await this.syncLatest();
    },
    async startManualCheck(): Promise<StartManualCheckResult> {
      if (this.isRunActive) {
        return {
          kind: "already_running",
          runId: this.latestRun?.id ?? null,
          requestId: null,
        };
      }

      this.isSubmitting = true;
      this.lastErrorMessage = null;
      this.lastErrorRequestId = null;
      this.beginSubmittingPhaseTracking();
      this.updatePolling();

      try {
        const result = await triggerManualRun();
        await this.syncLatest();

        if (!this.latestRun || this.latestRun.id !== result.run_id) {
          this.latestRun = buildPlaceholderRunningRun(result.run_id);
          this.lastSyncAt = Date.now();
          this.assumeRunningFromSubmission = true;
        }

        return {
          kind: "started",
          runId: result.run_id,
          reusedExistingRun: result.reused_existing_run,
        };
      } catch (error) {
        if (error instanceof ApiRequestError && error.code === "run_in_progress") {
          const runId = extractRunIdFromDetails(error.details);
          if (runId !== null) {
            this.latestRun = buildPlaceholderRunningRun(runId);
            this.lastSyncAt = Date.now();
            this.assumeRunningFromSubmission = true;
          }
          await this.syncLatest();

          return {
            kind: "already_running",
            runId: this.latestRun?.id ?? runId,
            requestId: error.requestId,
          };
        }

        if (error instanceof ApiRequestError) {
          this.lastErrorMessage = error.message;
          this.lastErrorRequestId = error.requestId;
          return {
            kind: "error",
            message: error.message,
            requestId: error.requestId,
          };
        }

        const fallbackMessage = "Unable to start an update check.";
        this.lastErrorMessage = fallbackMessage;
        this.lastErrorRequestId = null;
        return {
          kind: "error",
          message: fallbackMessage,
          requestId: null,
        };
      } finally {
        this.isSubmitting = false;
        this.clearSubmittingPhaseTimer();
        if (this.latestRun?.status !== "running") {
          this.assumeRunningFromSubmission = false;
        }
        this.updatePolling();
      }
    },
    reset(): void {
      this.stopPolling();
      this.clearSubmittingPhaseTimer();
      this.latestRun = null;
      this.isSubmitting = false;
      this.assumeRunningFromSubmission = false;
      this.lastErrorMessage = null;
      this.lastErrorRequestId = null;
      this.lastSyncAt = null;
    },
  },
});
