import { useState, useEffect } from 'react';
import { getFirestore, query, orderBy, limit, getDocs, where, Timestamp, type Firestore } from 'firebase/firestore';

import { useAuth } from '@/contexts/AuthContext';
import { tenantCollection } from '@/lib/tenancy/firestore';

export interface TableFreshness {
  tableName: string;
  displayName: string;
  lastRowTimestamp: Date | null;
  rowCountLast15Min: number;
  status: 'fresh' | 'stale' | 'critical' | 'unknown';
  loading: boolean;
}

export interface JobHealth {
  jobName: string;
  lastRunAt: Date | null;
  status: 'healthy' | 'warning' | 'critical' | 'unknown';
  dataSource: string;
}

const FRESH_THRESHOLD_MINUTES = 5;
const STALE_THRESHOLD_MINUTES = 15;

function getStatus(lastTimestamp: Date | null): 'fresh' | 'stale' | 'critical' | 'unknown' {
  if (!lastTimestamp) return 'unknown';
  
  const now = new Date();
  const diffMinutes = (now.getTime() - lastTimestamp.getTime()) / (1000 * 60);
  
  if (diffMinutes <= FRESH_THRESHOLD_MINUTES) return 'fresh';
  if (diffMinutes <= STALE_THRESHOLD_MINUTES) return 'stale';
  return 'critical';
}

async function fetchTableFreshness(db: Firestore, tenantId: string, tableName: string, displayName: string, timestampField: string): Promise<TableFreshness> {
  const now = new Date();
  const fifteenMinutesAgo = Timestamp.fromDate(new Date(now.getTime() - 15 * 60 * 1000));
  const collectionRef = tenantCollection(db, tenantId, tableName);

  const [latestSnapshot, countSnapshot] = await Promise.all([
    getDocs(query(collectionRef, orderBy(timestampField, 'desc'), limit(1))),
    getDocs(query(collectionRef, where(timestampField, '>=', fifteenMinutesAgo)))
  ]);

  const lastTs = !latestSnapshot.empty ? (latestSnapshot.docs[0].data()[timestampField] as Timestamp).toDate() : null;
  
  return {
    tableName,
    displayName,
    lastRowTimestamp: lastTs,
    rowCountLast15Min: countSnapshot.size,
    status: getStatus(lastTs),
    loading: false
  };
}

export function useDataFreshness() {
  const [tables, setTables] = useState<TableFreshness[]>([]);
  const [jobs, setJobs] = useState<JobHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const { tenantId } = useAuth();

  const fetchFreshness = async () => {
    if (!tenantId) return;
    const db = getFirestore();
    const tableConfigs = [
      { tableName: 'alpaca_option_snapshots', displayName: 'Options Snapshots', timestampField: 'inserted_at' },
      { tableName: 'news_events', displayName: 'News Events', timestampField: 'received_at' },
      { tableName: 'live_quotes', displayName: 'Live Quotes', timestampField: 'ts' },
      { tableName: 'market_data_1m', displayName: 'Market Data 1m', timestampField: 'ts' },
    ];

    const updates = await Promise.all(
      tableConfigs.map(config => fetchTableFreshness(db, tenantId, config.tableName, config.displayName, config.timestampField))
    );
    
    setTables(updates);

    const derivedJobs: JobHealth[] = updates.map(table => ({
      jobName: `${table.displayName.replace(' ', '')}Collector`,
      lastRunAt: table.lastRowTimestamp,
      status: table.status === 'fresh' ? 'healthy' : table.status === 'stale' ? 'warning' : 'critical',
      dataSource: table.tableName,
    }));
    
    setJobs(derivedJobs);
    setLoading(false);
    setLastRefresh(new Date());
  };

  useEffect(() => {
    fetchFreshness();
    const interval = setInterval(fetchFreshness, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, [tenantId]);

  return { tables, jobs, loading, lastRefresh, refresh: fetchFreshness };
}
