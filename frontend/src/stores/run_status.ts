import { defineStore } from "pinia";

import { listRuns, triggerManualRun, cancelRun, type RunListItem } from "@/features/runs";
import {
  createDefaultSafetyState,
  normalizeSafetyState,
  type ScrapeSafetyState,
} from "@/features/safety";
import { type PublicationItem } from "@/features/publications";
import { ApiRequestError } from "@/lib/api/errors";

export const RUN_STATUS_POLL_INTERVAL_MS = 15000;
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

export type CancelCheckResult =
  | { kind: "success" }
  | { kind: "error"; message: string };

let pollTimer: ReturnType<typeof setInterval> | null = null;
let syncPromise: Promise<void> | null = null;
let submittingPhaseTimer: ReturnType<typeof setTimeout> | null = null;
let eventSource: EventSource | null = null;
let activeStreamRunId: number | null = null;
const ACTIVE_STATUSES = new Set(["running", "resolving"]);

type StreamDisplayIdentifier = PublicationItem["display_identifier"];

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

function extractSafetyStateFromDetails(details: unknown): ScrapeSafetyState | null {
  if (!details || typeof details !== "object") {
    return null;
  }

  const candidate = (details as Record<string, unknown>).safety_state;
  if (!candidate || typeof candidate !== "object") {
    return null;
  }

  return normalizeSafetyState(candidate);
}

function isActiveStatus(value: string | null | undefined): boolean {
  return value !== undefined && value !== null && ACTIVE_STATUSES.has(value);
}

function parsePublicationCount(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.max(Math.trunc(value), 0);
  }
  return fallback;
}

function parseDisplayIdentifier(value: unknown): StreamDisplayIdentifier {
  if (!value || typeof value !== "object") {
    return null;
  }
  const payload = value as Record<string, unknown>;
  if (typeof payload.kind !== "string" || typeof payload.value !== "string" || typeof payload.label !== "string") {
    return null;
  }
  if (typeof payload.confidence_score !== "number" || !Number.isFinite(payload.confidence_score)) {
    return null;
  }
  const url = typeof payload.url === "string" ? payload.url : null;
  return {
    kind: payload.kind,
    value: payload.value,
    label: payload.label,
    url,
    confidence_score: payload.confidence_score,
  };
}

function withUpdatedDisplayIdentifier(
  items: PublicationItem[],
  update: {
    publicationId: number;
    displayIdentifier: StreamDisplayIdentifier;
  },
): PublicationItem[] {
  const { publicationId, displayIdentifier } = update;
  let changed = false;
  const next = items.map((item) => {
    if (item.publication_id !== publicationId) {
      return item;
    }
    changed = true;
    return { ...item, display_identifier: displayIdentifier };
  });
  return changed ? next : items;
}

function reconcileRunCounters(previous: RunListItem | null, next: RunListItem | null): RunListItem | null {
  if (previous === null || next === null) {
    return next;
  }
  if (previous.id !== next.id) {
    return next;
  }
  const previousCount = parsePublicationCount(previous.new_publication_count, 0);
  const nextCount = parsePublicationCount(next.new_publication_count, previousCount);
  return {
    ...next,
    new_publication_count: Math.max(previousCount, nextCount),
  };
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
    safetyState: createDefaultSafetyState() as ScrapeSafetyState,
    isSubmitting: false,
    assumeRunningFromSubmission: false,
    isPolling: false,
    lastErrorMessage: null as string | null,
    lastErrorRequestId: null as string | null,
    lastSyncAt: null as number | null,
    livePublications: [] as Array<PublicationItem>,
    scholarProgress: null as { visited: number; finished: number; total: number } | null,
  }),
  getters: {
    isRunActive(state): boolean {
      const s = state.latestRun?.status;
      return state.isSubmitting || s === "running" || s === "resolving";
    },
    isLikelyRunning(state): boolean {
      const s = state.latestRun?.status;
      return s === "running" || s === "resolving" || state.assumeRunningFromSubmission;
    },
    canStart(): boolean {
      return !this.isRunActive && !this.safetyState.cooldown_active;
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
      if (isActiveStatus(run?.status)) {
        this.assumeRunningFromSubmission = true;
      } else if (!this.isSubmitting) {
        this.assumeRunningFromSubmission = false;
      }
      this.updatePolling();
    },
    setSafetyState(value: unknown): void {
      this.safetyState = normalizeSafetyState(value);
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
        this.updateEventSource();
        return;
      }
      this.stopPolling();
      this.updateEventSource();
    },
    updateEventSource(): void {
      const targetRunId = isActiveStatus(this.latestRun?.status) ? this.latestRun?.id ?? null : null;
      if (activeStreamRunId === targetRunId) {
        return;
      }
      if (eventSource !== null) {
        eventSource.close();
        eventSource = null;
        activeStreamRunId = null;
      }
      if (targetRunId !== null) {
        if (typeof EventSource === "undefined") {
          return;
        }
        activeStreamRunId = targetRunId;
        this.livePublications = [];
        this.scholarProgress = null;
        eventSource = new EventSource(`/api/v1/runs/${targetRunId}/stream`);
        eventSource.addEventListener("publication_discovered", (e) => {
          try {
            const data = JSON.parse(e.data);
            if (this.latestRun && this.latestRun.id === targetRunId) {
              const baseline = parsePublicationCount(this.latestRun.new_publication_count, 0);
              const payloadCount = parsePublicationCount(data?.new_publication_count, baseline + 1);
              this.latestRun.new_publication_count = Math.max(baseline, payloadCount);
            }
            this.livePublications.unshift({
              publication_id: data.publication_id,
              scholar_profile_id: data.scholar_profile_id,
              scholar_label: data.scholar_label,
              title: data.title,
              pub_url: data.pub_url,
              first_seen_at: data.first_seen_at,
              year: null,
              citation_count: 0,
              venue_text: null,
              display_identifier: null,
              pdf_url: null,
              pdf_status: "untracked",
              pdf_attempt_count: 0,
              pdf_failure_reason: null,
              pdf_failure_detail: null,
              is_read: false,
              is_favorite: false,
              is_new_in_latest_run: true,
            });
            if (this.livePublications.length > 50) {
              this.livePublications.pop();
            }
          } catch (err) {
            console.error("Failed to parse SSE event", err);
          }
        });
        eventSource.addEventListener("identifier_updated", (e) => {
          try {
            const data = JSON.parse(e.data);
            const publicationId = parseRunId(data?.publication_id);
            const displayIdentifier = parseDisplayIdentifier(data?.display_identifier);
            if (publicationId === null || displayIdentifier === null) {
              return;
            }
            this.livePublications = withUpdatedDisplayIdentifier(
              this.livePublications,
              {
                publicationId,
                displayIdentifier,
              },
            );
          } catch (err) {
            console.error("Failed to parse SSE event", err);
          }
        });
        eventSource.addEventListener("scholar_progress", (e) => {
          try {
            const data = JSON.parse(e.data);
            const visited = typeof data.visited === "number" ? Math.max(0, Math.trunc(data.visited)) : null;
            const finished = typeof data.finished === "number" ? Math.max(0, Math.trunc(data.finished)) : null;
            const total = typeof data.total === "number" ? Math.max(1, Math.trunc(data.total)) : null;
            if (visited !== null && finished !== null && total !== null) {
              this.scholarProgress = { visited, finished, total };
            }
          } catch (err) {
            console.error("Failed to parse SSE event", err);
          }
        });
        eventSource.onerror = () => {
          // Reconnecting is handled automatically by EventSource,
          // but if it's permanently closed, we could do something here.
        };
      }
    },
    async syncLatest(): Promise<void> {
      if (syncPromise) {
        await syncPromise;
        return;
      }

      syncPromise = (async () => {
        try {
          const payload = await listRuns({ limit: 1 });
          const latest = reconcileRunCounters(this.latestRun, payload.runs[0] ?? null);
          this.latestRun = latest;
          this.safetyState = normalizeSafetyState(payload.safety_state);
          this.lastSyncAt = Date.now();
          this.lastErrorMessage = null;
          this.lastErrorRequestId = null;
          if (isActiveStatus(latest?.status)) {
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
      if (this.safetyState.cooldown_active) {
        const message =
          this.safetyState.recommended_action ||
          "Scrape safety cooldown is active; run start is temporarily blocked.";
        this.lastErrorMessage = message;
        this.lastErrorRequestId = null;
        return {
          kind: "error",
          message,
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
        this.safetyState = normalizeSafetyState(result.safety_state);
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

        if (error instanceof ApiRequestError && error.code === "scrape_cooldown_active") {
          const safetyState = extractSafetyStateFromDetails(error.details);
          if (safetyState) {
            this.safetyState = safetyState;
          }
          this.lastErrorMessage = error.message;
          this.lastErrorRequestId = error.requestId;
          return {
            kind: "error",
            message: error.message,
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
        if (!isActiveStatus(this.latestRun?.status)) {
          this.assumeRunningFromSubmission = false;
        }
        this.updatePolling();
      }
    },
    async cancelActiveCheck(): Promise<{ kind: "success" } | { kind: "error"; message: string }> {
      if (!this.latestRun || !isActiveStatus(this.latestRun.status)) {
        return { kind: "error", message: "No active run to cancel." };
      }
      try {
        const response = await cancelRun(this.latestRun.id);
        this.setLatestRun(reconcileRunCounters(this.latestRun, response.run));
        this.setSafetyState(response.safety_state);
        return { kind: "success" };
      } catch (error) {
        let errMessage = "Failed to cancel check.";
        if (error instanceof ApiRequestError) {
          errMessage = error.message;
        }
        return { kind: "error", message: errMessage };
      }
    },
    reset(): void {
      this.stopPolling();
      if (eventSource !== null) {
        eventSource.close();
        eventSource = null;
        activeStreamRunId = null;
      }
      this.clearSubmittingPhaseTimer();
      this.latestRun = null;
      this.isSubmitting = false;
      this.assumeRunningFromSubmission = false;
      this.lastErrorMessage = null;
      this.lastErrorRequestId = null;
      this.lastSyncAt = null;
      this.safetyState = createDefaultSafetyState();
      this.livePublications = [];
      this.scholarProgress = null;
    },
  },
});
