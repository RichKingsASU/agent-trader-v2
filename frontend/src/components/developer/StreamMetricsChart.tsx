import { useDataStreams } from '@/contexts/DataStreamContext';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar, Legend } from 'recharts';
import { Activity } from 'lucide-react';
import { useMemo } from 'react';

export const StreamMetricsChart = () => {
  const { metricsHistory, streams } = useDataStreams();

  const chartData = useMemo(() => {
    return metricsHistory.slice(-60).map((snapshot, idx) => ({
      time: idx,
      total: snapshot.totalMessagesPerSecond,
      ...snapshot.streamMetrics
    }));
  }, [metricsHistory]);

  const streamColors: Record<string, string> = {
    'price-polygon': 'hsl(var(--chart-1))',
    'options-opra': 'hsl(var(--chart-2))',
    'news-benzinga': 'hsl(var(--chart-3))',
    'account-tda': 'hsl(var(--chart-4))',
    'level2-polygon': 'hsl(var(--chart-5))'
  };

  const stats = useMemo(() => {
    const totalMps = streams.reduce((sum, s) => sum + s.messagesPerSecond, 0);
    const avgLatency = streams.length > 0 
      ? streams.reduce((sum, s) => sum + s.latencyMs, 0) / streams.length 
      : 0;
    const totalErrors = streams.reduce((sum, s) => sum + s.errorCount, 0);
    const totalMessages = streams.reduce((sum, s) => sum + s.messageCount, 0);
    return { totalMps, avgLatency, totalErrors, totalMessages };
  }, [streams]);

  return (
    <div className="space-y-4">
      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold font-mono">{stats.totalMps}</div>
            <p className="text-xs text-muted-foreground">Messages/sec</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold font-mono">{stats.avgLatency.toFixed(0)}ms</div>
            <p className="text-xs text-muted-foreground">Avg Latency</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className={`text-2xl font-bold font-mono ${stats.totalErrors > 0 ? 'text-destructive' : ''}`}>
              {stats.totalErrors}
            </div>
            <p className="text-xs text-muted-foreground">Total Errors</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold font-mono">
              {stats.totalMessages > 1000000 
                ? `${(stats.totalMessages / 1000000).toFixed(1)}M` 
                : stats.totalMessages > 1000 
                  ? `${(stats.totalMessages / 1000).toFixed(1)}K`
                  : stats.totalMessages}
            </div>
            <p className="text-xs text-muted-foreground">Total Messages</p>
          </CardContent>
        </Card>
      </div>

      {/* Messages Per Second Chart */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Messages Per Second (Last 60s)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="colorTotal" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="time" hide />
                <YAxis width={40} fontSize={10} tickFormatter={(v) => v.toString()} />
                <Tooltip 
                  contentStyle={{ 
                    backgroundColor: 'hsl(var(--card))', 
                    border: '1px solid hsl(var(--border))',
                    borderRadius: '8px'
                  }}
                  labelFormatter={() => ''}
                />
                <Area 
                  type="monotone" 
                  dataKey="total" 
                  stroke="hsl(var(--primary))" 
                  fill="url(#colorTotal)" 
                  strokeWidth={2}
                  name="Total"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Per-Stream Breakdown */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Stream Breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData.slice(-20)}>
                <XAxis dataKey="time" hide />
                <YAxis width={40} fontSize={10} />
                <Tooltip 
                  contentStyle={{ 
                    backgroundColor: 'hsl(var(--card))', 
                    border: '1px solid hsl(var(--border))',
                    borderRadius: '8px'
                  }}
                />
                <Legend wrapperStyle={{ fontSize: '10px' }} />
                {streams.map(stream => (
                  <Bar 
                    key={stream.id}
                    dataKey={stream.id}
                    stackId="a"
                    fill={streamColors[stream.id] || 'hsl(var(--muted))'}
                    name={stream.name}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
