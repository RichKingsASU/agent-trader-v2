import { useDataFreshness } from '@/hooks/useDataFreshness';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { RefreshCw, Activity, CheckCircle2, AlertTriangle, XCircle, Clock, Info } from 'lucide-react';
import { formatDistanceToNow, differenceInMinutes } from 'date-fns';

function getHealthScore(status: string): number {
  switch (status) {
    case 'healthy': return 100;
    case 'warning': return 60;
    case 'critical': return 20;
    default: return 0;
  }
}

function HealthBar({ score }: { score: number }) {
  const color = score >= 80 ? 'bg-[hsl(var(--bull))]' 
              : score >= 50 ? 'bg-[hsl(var(--warning))]' 
              : 'bg-[hsl(var(--bear))]';
  
  return (
    <div className="w-full h-2 bg-muted rounded-full overflow-hidden">
      <div 
        className={`h-full transition-all duration-500 ${color}`}
        style={{ width: `${score}%` }}
      />
    </div>
  );
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'healthy':
      return <CheckCircle2 className="h-6 w-6 text-[hsl(var(--bull))]" />;
    case 'warning':
      return <AlertTriangle className="h-6 w-6 text-[hsl(var(--warning))]" />;
    case 'critical':
      return <XCircle className="h-6 w-6 text-[hsl(var(--bear))]" />;
    default:
      return <Clock className="h-6 w-6 text-muted-foreground" />;
  }
}

export default function JobHealth() {
  const { jobs, tables, loading, lastRefresh, refresh } = useDataFreshness();

  const overallScore = jobs.length > 0 
    ? Math.round(jobs.reduce((acc, job) => acc + getHealthScore(job.status), 0) / jobs.length)
    : 0;

  const healthyCount = jobs.filter(j => j.status === 'healthy').length;
  const warningCount = jobs.filter(j => j.status === 'warning').length;
  const criticalCount = jobs.filter(j => j.status === 'critical').length;

  return (
    <div className="flex flex-col h-full p-6 space-y-6 overflow-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Job Health Monitor</h1>
          <p className="text-sm text-muted-foreground">
            Read-only view derived from data freshness
          </p>
        </div>
        <Button onClick={refresh} disabled={loading} variant="outline" size="sm">
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Overall Health */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            Overall System Health
          </CardTitle>
          <CardDescription>
            Last checked: {formatDistanceToNow(lastRefresh, { addSuffix: true })}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-8">
            <div className="flex-1">
              <div className="flex items-baseline gap-2 mb-2">
                <span className="text-5xl font-bold number-mono">{overallScore}</span>
                <span className="text-xl text-muted-foreground">/ 100</span>
              </div>
              <HealthBar score={overallScore} />
            </div>
            <div className="grid grid-cols-3 gap-6 text-center">
              <div>
                <div className="text-2xl font-bold text-[hsl(var(--bull))] number-mono">{healthyCount}</div>
                <div className="text-xs text-muted-foreground">Healthy</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-[hsl(var(--warning))] number-mono">{warningCount}</div>
                <div className="text-xs text-muted-foreground">Warning</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-[hsl(var(--bear))] number-mono">{criticalCount}</div>
                <div className="text-xs text-muted-foreground">Critical</div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Info Banner */}
      <Card className="border-primary/20 bg-primary/5">
        <CardContent className="pt-4">
          <div className="flex items-start gap-3">
            <Info className="h-5 w-5 text-primary mt-0.5" />
            <div>
              <p className="font-medium">Read-Only Monitoring</p>
              <p className="text-sm text-muted-foreground">
                Job health is derived from data freshness in Firestore collections. No direct Cloud Run access required.
                A job is considered healthy if its data source has received new rows within the last 5 minutes.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Job Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {jobs.map(job => {
          const tableInfo = tables.find(t => t.tableName === job.dataSource);
          const minutesSinceUpdate = job.lastRunAt 
            ? differenceInMinutes(new Date(), job.lastRunAt)
            : null;

          return (
            <Card key={job.jobName} className="relative overflow-hidden">
              <div 
                className={`absolute top-0 left-0 w-1 h-full ${
                  job.status === 'healthy' ? 'bg-[hsl(var(--bull))]' :
                  job.status === 'warning' ? 'bg-[hsl(var(--warning))]' :
                  job.status === 'critical' ? 'bg-[hsl(var(--bear))]' :
                  'bg-muted'
                }`} 
              />
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base flex items-center gap-2">
                    <StatusIcon status={job.status} />
                    {job.jobName}
                  </CardTitle>
                  <Badge 
                    className={
                      job.status === 'healthy' ? 'bg-[hsl(var(--bull))] text-[hsl(var(--bull-foreground))]' :
                      job.status === 'warning' ? 'bg-[hsl(var(--warning))] text-[hsl(var(--warning-foreground))]' :
                      job.status === 'critical' ? 'bg-[hsl(var(--bear))] text-[hsl(var(--bear-foreground))]' :
                      ''
                    }
                  >
                    {job.status.toUpperCase()}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Data Source</span>
                    <span className="number-mono">{job.dataSource}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-muted-foreground">Last Data</span>
                    <span>
                      {job.lastRunAt 
                        ? formatDistanceToNow(job.lastRunAt, { addSuffix: true })
                        : 'Never'}
                    </span>
                  </div>
                  {minutesSinceUpdate !== null && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Minutes Since Update</span>
                      <span className={`number-mono ${
                        minutesSinceUpdate <= 5 ? 'text-[hsl(var(--bull))]' :
                        minutesSinceUpdate <= 15 ? 'text-[hsl(var(--warning))]' :
                        'text-[hsl(var(--bear))]'
                      }`}>
                        {minutesSinceUpdate}m
                      </span>
                    </div>
                  )}
                  {tableInfo && (
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">Rows (15m)</span>
                      <span className="number-mono">{tableInfo.rowCountLast15Min}</span>
                    </div>
                  )}
                  <HealthBar score={getHealthScore(job.status)} />
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
