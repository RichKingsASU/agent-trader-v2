import { useState, useEffect } from 'react';
import { getFirestore, query, orderBy, limit, where, getDocs, Timestamp } from 'firebase/firestore';

import { useAuth } from '@/contexts/AuthContext';
import { tenantCollection } from '@/lib/tenancy/firestore';

export interface NewsEvent {
  id: string;
  source: string;
  headline: string;
  body: string | null;
  url: string | null;
  symbol: string | null;
  category: string | null;
  sentiment: string | null;
  importance: number | null;
  event_ts: Timestamp | null;
  received_at: Timestamp;
}

export interface NewsFilters {
  source: string | null;
  symbol: string | null;
  limit: number;
}

export function useNewsEvents(initialFilters?: Partial<NewsFilters>) {
  const [filters, setFilters] = useState<NewsFilters>({
    source: null,
    symbol: null,
    limit: 100,
    ...initialFilters
  });
  const [events, setEvents] = useState<NewsEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { tenantId } = useAuth();

  const fetchEvents = async () => {
    setLoading(true);
    setError(null);

    try {
      if (!tenantId) return;
      const db = getFirestore();
      const eventsCollection = tenantCollection(db, tenantId, 'news_events');
      
      let q = query(eventsCollection, orderBy('received_at', 'desc'), limit(filters.limit));

      if (filters.source) {
        q = query(q, where('source', '==', filters.source));
      }

      if (filters.symbol) {
        q = query(q, where('symbol', '==', filters.symbol));
      }

      const snapshot = await getDocs(q);
      const newEvents = snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() } as NewsEvent));
      setEvents(newEvents);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch news events');
      setEvents([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEvents();
  }, [filters, tenantId]);

  const updateFilters = (newFilters: Partial<NewsFilters>) => {
    setFilters(prev => ({ ...prev, ...newFilters }));
  };

  return {
    events,
    filters,
    updateFilters,
    loading,
    error,
    refresh: fetchEvents
  };
}
