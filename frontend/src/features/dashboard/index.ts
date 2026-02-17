import {
  listPublications,
  type PublicationItem,
  type PublicationMode,
} from "@/features/publications";
import { listQueueItems, listRuns, type RunListItem } from "@/features/runs";

export interface QueueHealth {
  queued: number;
  retrying: number;
  dropped: number;
}

export interface DashboardSnapshot {
  newCount: number;
  totalCount: number;
  mode: PublicationMode;
  latestRun: RunListItem | null;
  recentRuns: RunListItem[];
  recentPublications: PublicationItem[];
  queue: QueueHealth;
}

function countQueueStatuses(statuses: string[]): QueueHealth {
  return statuses.reduce<QueueHealth>(
    (acc, status) => {
      if (status === "queued") {
        acc.queued += 1;
      } else if (status === "retrying") {
        acc.retrying += 1;
      } else if (status === "dropped") {
        acc.dropped += 1;
      }
      return acc;
    },
    { queued: 0, retrying: 0, dropped: 0 },
  );
}

export async function fetchDashboardSnapshot(): Promise<DashboardSnapshot> {
  const [publications, runs, queueItems] = await Promise.all([
    listPublications({ mode: "new", limit: 20 }),
    listRuns({ limit: 5 }),
    listQueueItems(200),
  ]);

  const queueHealth = countQueueStatuses(queueItems.map((item) => item.status));

  return {
    newCount: publications.new_count,
    totalCount: publications.total_count,
    mode: publications.mode,
    latestRun: runs[0] ?? null,
    recentRuns: runs,
    recentPublications: publications.publications,
    queue: queueHealth,
  };
}
