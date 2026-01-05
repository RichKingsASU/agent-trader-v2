import { useState, useEffect, useMemo } from 'react';
import { getFirestore, query, where, orderBy, limit, getDocs, Timestamp } from 'firebase/firestore';

import { useAuth } from '@/contexts/AuthContext';
import { tenantCollection } from '@/lib/tenancy/firestore';

export interface OptionSnapshot {
  option_symbol: string;
  underlying_symbol: string;
  snapshot_time: Timestamp;
  inserted_at: Timestamp;
  payload: {
    strike?: number;
    expiration?: string;
    option_type?: 'call' | 'put';
    bid?: number;
    ask?: number;
    last?: number;
    volume?: number;
    open_interest?: number;
    iv?: number;
    delta?: number;
    gamma?: number;
    theta?: number;
    vega?: number;
    [key: string]: unknown;
  };
}

export interface SnapshotFilters {
  symbol: string;
  optionType: 'all' | 'call' | 'put';
  strikeMin: number | null;
  strikeMax: number | null;
  expiration: string | null;
  timeWindowMinutes: number;
}

const DEFAULT_FILTERS: SnapshotFilters = {
  symbol: 'SPY',
  optionType: 'all',
  strikeMin: null,
  strikeMax: null,
  expiration: null,
  timeWindowMinutes: 60,
};

export function useOptionsSnapshots(initialFilters?: Partial<SnapshotFilters>) {
  const [filters, setFilters] = useState<SnapshotFilters>({ ...DEFAULT_FILTERS, ...initialFilters });
  const [snapshots, setSnapshots] = useState<OptionSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const { tenantId } = useAuth();

  const fetchSnapshots = async () => {
    setLoading(true);
    setError(null);

    try {
      if (!tenantId) return;
      const db = getFirestore();
      const now = new Date();
      const timeWindowStart = Timestamp.fromDate(new Date(now.getTime() - filters.timeWindowMinutes * 60 * 1000));

      let q = query(
        tenantCollection(db, tenantId, 'alpaca_option_snapshots'),
        where('underlying_symbol', '==', filters.symbol),
        where('snapshot_time', '>=', timeWindowStart),
        orderBy('snapshot_time', 'desc'),
        limit(500)
      );

      const snapshot = await getDocs(q);
      const data = snapshot.docs.map(doc => doc.data() as OptionSnapshot);
      
      setTotalCount(snapshot.size);

      // Client-side filtering for JSONB fields
      let filtered = data;

      if (filters.optionType !== 'all') {
        filtered = filtered.filter(s => s.payload?.option_type === filters.optionType);
      }

      if (filters.strikeMin !== null) {
        filtered = filtered.filter(s => (s.payload?.strike || 0) >= filters.strikeMin!);
      }

      if (filters.strikeMax !== null) {
        filtered = filtered.filter(s => (s.payload?.strike || 0) <= filters.strikeMax!);
      }

      if (filters.expiration) {
        filtered = filtered.filter(s => s.payload?.expiration === filters.expiration);
      }

      setSnapshots(filtered);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch snapshots');
      setSnapshots([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSnapshots();
  }, [filters, tenantId]);

  const updateFilters = (newFilters: Partial<SnapshotFilters>) => {
    setFilters(prev => ({ ...prev, ...newFilters }));
  };

  // Get unique expirations from current data
  const availableExpirations = useMemo(() => {
    const exps = new Set<string>();
    snapshots.forEach(s => {
      if (s.payload?.expiration) exps.add(s.payload.expiration);
    });
    return Array.from(exps).sort();
  }, [snapshots]);

  return {
    snapshots,
    filters,
    updateFilters,
    loading,
    error,
    totalCount,
    availableExpirations,
    refresh: fetchSnapshots
  };
}
