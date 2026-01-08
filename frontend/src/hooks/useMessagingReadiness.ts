import { useCallback, useEffect, useState } from 'react';
import {
  defaultMockMessagingReadinessAdapter,
  type MessagingReadinessAdapter,
  type MessagingReadinessSnapshot,
} from '@/lib/observability/messaging';

type UseMessagingReadinessResult = {
  snapshot: MessagingReadinessSnapshot;
  loading: boolean;
  lastRefresh: Date;
  refresh: () => Promise<void>;
};

export function useMessagingReadiness(
  adapter: MessagingReadinessAdapter = defaultMockMessagingReadinessAdapter
): UseMessagingReadinessResult {
  const [snapshot, setSnapshot] = useState<MessagingReadinessSnapshot>({
    generatedAt: new Date(0),
    source: 'mock',
    topics: [],
  });
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await adapter.getSnapshot();
      setSnapshot(next);
      setLastRefresh(new Date());
    } finally {
      setLoading(false);
    }
  }, [adapter]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { snapshot, loading, lastRefresh, refresh };
}

