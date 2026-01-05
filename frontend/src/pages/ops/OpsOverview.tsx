import { useDataFreshness } from '@/hooks/useDataFreshness';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { RefreshCw, Database, Clock, TrendingUp, AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

function StatusBadge({ status }: { status: 'fresh' | 'stale' | 'critical' | 'unknown' | 'healthy' | 'warning' }) {
  const config = {
    fresh: { label: 'Fresh', className: 'bg-[hsl(var(--bull))] text-[hsl(var(--bull-foreground))]' },
    healthy: { label: 'Healthy', className: 'bg-[hsl(var(--bull))] text-[hsl(var(--bull-foreground))]' },
    stale: { label: 'Stale', className: 'bg-[hsl(var(--warning))] text-[hsl(var(--warning-foreground))]' },
    warning: { label: 'Warning', className: 'bg-[hsl(var(--warning))] text-[hsl(var(--warning-foreground))]' },
    critical: { label: 'Critical', className: 'bg-[hsl(var(--bear))] text-[hsl(var(--bear-foreground))]' },
    unknown: { label: 'Unknown', className: 'bg-muted text-muted-foreground' },
  };

  const { label, className } = config[status] || config.unknown;

  return <Badge className={className}>{label}</Badge>;
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'fresh':
    case 'healthy':
      return <CheckCircle2 className="h-5 w-5 text-[hsl(var(--bull))]" />;
    case 'stale':
    case 'warning':
      return <AlertTriangle className="h-5 w-5 text-[hsl(var(--warning))]" />;
    case 'critical':
      return <XCircle className="h-5 w-5 text-[hsl(var(--bear))]" />;
    default:
      return <Clock className="h-5 w-5 text-muted-foreground" />;
  }
}

export default function OpsOverview() {
  const { tables, jobs, loading, lastRefresh, refresh } = useDataFreshness();

  return (
    <div className="flex flex-col h-full p-6 space-y-6 overflow-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Ops Overview</h1>
          <p className="text-sm text-muted-foreground">
            Last refreshed: {formatDistanceToNow(lastRefresh, { addSuffix: true })}
          </p>
        </div>
        <Button onClick={refresh} disabled={loading} variant="outline" size="sm">
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Tables Monitored</p>
                <p className="text-3xl font-bold number-mono">{tables.length}</p>
              </div>
              <Database className="h-8 w-8 text-primary" />
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Fresh</p>
                <p className="text-3xl font-bold number-mono text-[hsl(var(--bull))]">
                  {tables.filter(t => t.status === 'fresh').length}
                </p>
              </div>
              <CheckCircle2 className="h-8 w-8 text-[hsl(var(--bull))]" />
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Stale</p>
                <p className="text-3xl font-bold number-mono text-[hsl(var(--warning))]">
                  {tables.filter(t => t.status === 'stale').length}
                </p>
              </div>
              <AlertTriangle className="h-8 w-8 text-[hsl(var(--warning))]" />
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Critical</p>
                <p className="text-3xl font-bold number-mono text-[hsl(var(--bear))]">
                  {tables.filter(t => t.status === 'critical').length}
                </p>
              </div>
              <XCircle className="h-8 w-8 text-[hsl(var(--bear))]" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Table Freshness Grid */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Table Freshness
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {tables.map(table => (
              <div
                key={table.tableName}
                className="flex items-center justify-between p-4 rounded-lg border bg-card"
              >
                <div className="flex items-center gap-3">
                  <StatusIcon status={table.status} />
                  <div>
                    <p className="font-medium">{table.displayName}</p>
                    <p className="text-xs text-muted-foreground number-mono">{table.tableName}</p>
                  </div>
                </div>
                <div className="text-right">
                  <StatusBadge status={table.status} />
                  <p className="text-xs text-muted-foreground mt-1">
                    {table.lastRowTimestamp 
                      ? formatDistanceToNow(table.lastRowTimestamp, { addSuffix: true })
                      : 'No data'}
                  </p>
                  <p className="text-xs text-muted-foreground number-mono">
                    {table.rowCountLast15Min} rows / 15m
                  </p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Job Health */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5" />
            Job Health (Derived)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {jobs.map(job => (
              <div
                key={job.jobName}
                className="flex items-center justify-between p-3 rounded-lg border bg-card"
              >
                <div className="flex items-center gap-3">
                  <StatusIcon status={job.status} />
                  <div>
                    <p className="font-medium">{job.jobName}</p>
                    <p className="text-xs text-muted-foreground">
                      Source: {job.dataSource}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <StatusBadge status={job.status} />
                  <p className="text-xs text-muted-foreground mt-1">
                    {job.lastRunAt
                      ? formatDistanceToNow(job.lastRunAt, { addSuffix: true })
                      : 'Never'}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
