export type TopicHealthStatus = 'healthy' | 'warning' | 'critical' | 'unknown';

export type MessageCounters = {
  /** Messages observed in the last 1 minute */
  last1m: number;
  /** Messages observed in the last 15 minutes */
  last15m: number;
  /** Messages observed in the last 1 hour */
  last1h: number;
  /** Lifetime total (or since boot) */
  total: number;
};

export type TopicReadiness = {
  /** Pub/Sub topic name (or logical stream name) */
  topic: string;
  /** Optional display name for the UI */
  displayName?: string;
  /** Health indicator (derived in the future from lag/errors/last-seen) */
  status: TopicHealthStatus;
  /** Last time a message was observed (null/undefined means "never") */
  lastSeenAt?: Date | null;
  /** Message counters (placeholders until wired to live data) */
  counters: MessageCounters;
  /** Optional note for operators */
  note?: string;
};

export type MessagingReadinessSnapshot = {
  /** Timestamp when the snapshot was generated */
  generatedAt: Date;
  /** Where the snapshot came from (mock for now) */
  source: 'mock';
  /** Topic readiness list (safe to be empty) */
  topics: TopicReadiness[];
};

export interface MessagingReadinessAdapter {
  getSnapshot(): Promise<MessagingReadinessSnapshot>;
}

const emptyCounters: MessageCounters = {
  last1m: 0,
  last15m: 0,
  last1h: 0,
  total: 0,
};

/**
 * Mock adapter (intentionally non-active).
 * - No environment assumptions
 * - No network connections
 * - Safe defaults (renders with zero data)
 */
export function createMockMessagingReadinessAdapter(
  seed?: Partial<Pick<MessagingReadinessSnapshot, 'topics'>>
): MessagingReadinessAdapter {
  const topics = seed?.topics ?? [];

  return {
    async getSnapshot() {
      return {
        generatedAt: new Date(),
        source: 'mock',
        topics: topics.map((t) => ({
          topic: t.topic,
          displayName: t.displayName,
          status: t.status ?? 'unknown',
          lastSeenAt: t.lastSeenAt ?? null,
          counters: t.counters ?? emptyCounters,
          note: t.note,
        })),
      };
    },
  };
}

export const defaultMockMessagingReadinessAdapter = createMockMessagingReadinessAdapter();

