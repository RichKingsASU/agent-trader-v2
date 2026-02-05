import { useEffect, useState } from 'react';
import { RefreshCw, Clock, Database } from 'lucide-react';

import { useDataStreams } from '@/contexts/DataStreamContext';
import { useExchanges } from '@/contexts/ExchangeContext';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

interface FreshnessItem {
  name: string;
  source: string;
  lastUpdate: Date | null;
  refreshRate: string;
  isRealtime: boolean;
  isSupabase: boolean;
}

const getFreshnessStatus = (lastUpdate: Date | null, isRealtime: boolean) => {
  if (!lastUpdate) return { color: 'bg-muted', label: 'No Data' };

  const ageMs = Date.now() - lastUpdate.getTime();
  const ageSec = ageMs / 1000;
  const ageMin = ageSec / 60;
  const ageHours = ageMin / 60;
  const ageDays = ageHours / 24;

  if (!isRealtime) {
    if (ageDays < 1) return { color: 'bg-emerald-500', label: 'Fresh' };
    if (ageDays < 7) return { color: 'bg-emerald-400', label: 'Recent' };
    if (ageDays < 30) return { color: 'bg-amber-500', label: 'Stale' };
    return { color: 'bg-destructive', label: 'Outdated' };
  }

  if (ageSec < 2) return { color: 'bg-emerald-500', label: 'Live' };
  if (ageSec < 10) return { color: 'bg-emerald-400', label: 'Fresh' };
  if (ageSec < 30) return { color: 'bg-amber-500', label: 'Stale' };
  return { color: 'bg-destructive', label: 'Outdated' };
};

const formatAge = (lastUpdate: Date | null) => {
  if (!lastUpdate) return 'Never';
  const ageSec = (Date.now() - lastUpdate.getTime()) / 1000;
  if (ageSec < 1) return '< 1s ago';
  if (ageSec < 60) return `${Math.floor(ageSec)}s ago`;
  if (ageSec < 3600) return `${Math.floor(ageSec / 60)}m ago`;
  if (ageSec < 86400) return `${Math.floor(ageSec / 3600)}h ago`;
  return `${Math.floor(ageSec / 86400)}d ago`;
};

export const DataFreshnessGrid = () => {
  const { streams, reconnectStream } = useDataStreams();
  const { getExchangeById } = useExchanges();
  const [, forceUpdate] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => forceUpdate((n) => n + 1), 1000);
    return () => clearInterval(interval);
  }, []);

  const freshnessItems: FreshnessItem[] = streams.map((stream: any) => ({
    name: stream.name,
    source: stream.isSupabase ? 'Supabase' : getExchangeById(stream.exchange)?.displayName || stream.exchange,
    lastUpdate: stream.lastMessage,
    refreshRate: stream.isSupabase
      ? 'Real-time Push'
      : stream.type === 'price' || stream.type === 'level2'
        ? 'Real-time'
        : stream.type === 'account'
          ? '15s'
          : stream.type === 'options'
            ? '5s'
            : 'Push',
    isRealtime: !stream.isSupabase && (stream.type === 'price' || stream.type === 'level2'),
    isSupabase: stream.isSupabase || false,
  }));

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Clock className="h-4 w-4" />
          Data Freshness
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          <div className="grid grid-cols-5 gap-2 text-xs text-muted-foreground font-medium pb-2 border-b">
            <span>Data Type</span>
            <span>Source</span>
            <span>Last Update</span>
            <span>Refresh Rate</span>
            <span>Status</span>
          </div>
          {freshnessItems.map((item, idx) => {
            const freshness = getFreshnessStatus(item.lastUpdate, item.isRealtime);
            const stream = streams[idx];

            return (
              <div key={`${item.name}-${idx}`} className="grid grid-cols-5 gap-2 items-center py-2 border-b border-border/50 last:border-0">
                <span className="font-medium text-sm flex items-center gap-1.5">
                  {item.isSupabase && <Database className="h-3 w-3 text-muted-foreground" />}
                  {item.name}
                </span>
                <span className="text-sm text-muted-foreground">{item.source}</span>
                <span className="font-mono text-sm">{formatAge(item.lastUpdate)}</span>
                <span className="text-sm text-muted-foreground">{item.refreshRate}</span>
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="text-xs flex items-center gap-1">
                    <span className={`h-2 w-2 rounded-full ${freshness.color}`} />
                    {freshness.label}
                  </Badge>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => stream && reconnectStream(stream.id)}
                    aria-label={`Reconnect ${item.name}`}
                  >
                    <RefreshCw className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            );
          })}

          {freshnessItems.length === 0 && (
            <div className="text-center py-8 text-muted-foreground text-sm">No data streams connected</div>
          )}
        </div>
      </CardContent>
    </Card>
  );
};

