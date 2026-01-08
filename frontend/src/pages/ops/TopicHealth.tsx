import { useMemo } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { RefreshCw, Radio, CheckCircle2, AlertTriangle, XCircle, Clock } from 'lucide-react';

import { useMessagingReadiness } from '@/hooks/useMessagingReadiness';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { TopicHealthStatus, TopicReadiness } from '@/lib/observability/messaging';

function HealthBadge({ status }: { status: TopicHealthStatus }) {
  const config: Record<TopicHealthStatus, { label: string; className: string }> = {
    healthy: { label: 'Healthy', className: 'bg-[hsl(var(--bull))] text-[hsl(var(--bull-foreground))]' },
    warning: { label: 'Warning', className: 'bg-[hsl(var(--warning))] text-[hsl(var(--warning-foreground))]' },
    critical: { label: 'Critical', className: 'bg-[hsl(var(--bear))] text-[hsl(var(--bear-foreground))]' },
    unknown: { label: 'Unknown', className: 'bg-muted text-muted-foreground' },
  };

  const { label, className } = config[status];
  return <Badge className={className}>{label}</Badge>;
}

function HealthIcon({ status }: { status: TopicHealthStatus }) {
  switch (status) {
    case 'healthy':
      return <CheckCircle2 className="h-5 w-5 text-[hsl(var(--bull))]" />;
    case 'warning':
      return <AlertTriangle className="h-5 w-5 text-[hsl(var(--warning))]" />;
    case 'critical':
      return <XCircle className="h-5 w-5 text-[hsl(var(--bear))]" />;
    default:
      return <Clock className="h-5 w-5 text-muted-foreground" />;
  }
}

function LastSeen({ at }: { at?: Date | null }) {
  if (!at) return <span className="text-xs text-muted-foreground">Never</span>;
  return (
    <span className="text-xs text-muted-foreground">
      {formatDistanceToNow(at, { addSuffix: true })}
    </span>
  );
}

function TopicRow({ topic }: { topic: TopicReadiness }) {
  return (
    <div className="flex items-center justify-between p-4 rounded-lg border bg-card">
      <div className="flex items-center gap-3 min-w-0">
        <HealthIcon status={topic.status} />
        <div className="min-w-0">
          <p className="font-medium truncate">{topic.displayName ?? topic.topic}</p>
          <p className="text-xs text-muted-foreground number-mono truncate">{topic.topic}</p>
          {topic.note ? (
            <p className="text-xs text-muted-foreground mt-1 truncate">{topic.note}</p>
          ) : null}
        </div>
      </div>

      <div className="text-right flex-shrink-0">
        <HealthBadge status={topic.status} />
        <div className="mt-1">
          <LastSeen at={topic.lastSeenAt} />
        </div>
        <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
          <div className="text-muted-foreground">1m</div>
          <div className="number-mono">{topic.counters.last1m}</div>
          <div className="text-muted-foreground">15m</div>
          <div className="number-mono">{topic.counters.last15m}</div>
          <div className="text-muted-foreground">1h</div>
          <div className="number-mono">{topic.counters.last1h}</div>
          <div className="text-muted-foreground">Total</div>
          <div className="number-mono">{topic.counters.total}</div>
        </div>
      </div>
    </div>
  );
}

export default function TopicHealth() {
  const { snapshot, loading, lastRefresh, refresh } = useMessagingReadiness();

  const summary = useMemo(() => {
    const topics = snapshot.topics ?? [];
    const counts = {
      total: topics.length,
      healthy: topics.filter((t) => t.status === 'healthy').length,
      warning: topics.filter((t) => t.status === 'warning').length,
      critical: topics.filter((t) => t.status === 'critical').length,
      unknown: topics.filter((t) => t.status === 'unknown').length,
    };

    const counters = topics.reduce(
      (acc, t) => ({
        last1m: acc.last1m + (t.counters?.last1m ?? 0),
        last15m: acc.last15m + (t.counters?.last15m ?? 0),
        last1h: acc.last1h + (t.counters?.last1h ?? 0),
        total: acc.total + (t.counters?.total ?? 0),
      }),
      { last1m: 0, last15m: 0, last1h: 0, total: 0 }
    );

    const mostRecent = topics
      .map((t) => t.lastSeenAt ?? null)
      .filter((d): d is Date => d instanceof Date)
      .sort((a, b) => b.getTime() - a.getTime())[0];

    return { counts, counters, mostRecent };
  }, [snapshot.topics]);

  return (
    <div className="flex flex-col h-full p-6 space-y-6 overflow-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Topic Health (Scaffold)</h1>
          <p className="text-sm text-muted-foreground">
            Mock readiness snapshot — no live Pub/Sub wiring yet
          </p>
        </div>
        <Button onClick={refresh} disabled={loading} variant="outline" size="sm">
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Topics</p>
                <p className="text-3xl font-bold number-mono">{summary.counts.total}</p>
              </div>
              <Radio className="h-8 w-8 text-primary" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Messages (15m)</p>
                <p className="text-3xl font-bold number-mono">{summary.counters.last15m}</p>
              </div>
              <Radio className="h-8 w-8 text-primary" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div>
              <p className="text-sm text-muted-foreground">Most Recent Message</p>
              <p className="text-lg font-semibold">
                {summary.mostRecent ? formatDistanceToNow(summary.mostRecent, { addSuffix: true }) : 'No data'}
              </p>
              <p className="text-xs text-muted-foreground">
                Snapshot: {formatDistanceToNow(lastRefresh, { addSuffix: true })}
              </p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
              <div className="text-muted-foreground">Healthy</div>
              <div className="number-mono text-[hsl(var(--bull))]">{summary.counts.healthy}</div>
              <div className="text-muted-foreground">Warning</div>
              <div className="number-mono text-[hsl(var(--warning))]">{summary.counts.warning}</div>
              <div className="text-muted-foreground">Critical</div>
              <div className="number-mono text-[hsl(var(--bear))]">{summary.counts.critical}</div>
              <div className="text-muted-foreground">Unknown</div>
              <div className="number-mono">{summary.counts.unknown}</div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Topics */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Radio className="h-5 w-5" />
            Topics
          </CardTitle>
          <CardDescription>
            Placeholder readiness rows for counters, last-seen timestamps, and health indicators.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {snapshot.topics.length === 0 ? (
            <div className="p-6 rounded-lg border bg-card text-sm text-muted-foreground">
              No topics configured yet. This page is scaffolding-only and will light up instantly once a real adapter
              supplies topic snapshots.
            </div>
          ) : (
            <div className="space-y-3">
              {snapshot.topics.map((t) => (
                <TopicRow key={t.topic} topic={t} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

