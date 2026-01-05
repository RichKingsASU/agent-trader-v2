import { useDataStreams, DataStream, StreamStatus } from '@/contexts/DataStreamContext';
import { useExchanges } from '@/contexts/ExchangeContext';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { 
  Radio, BarChart3, Newspaper, BookOpen, TrendingUp, Wallet,
  Pause, Play, RefreshCw, X, Wifi, WifiOff, AlertCircle, Loader2
} from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

const streamTypeIcons: Record<string, React.ReactNode> = {
  price: <Radio className="h-4 w-4" />,
  options: <BarChart3 className="h-4 w-4" />,
  news: <Newspaper className="h-4 w-4" />,
  level2: <BookOpen className="h-4 w-4" />,
  trades: <TrendingUp className="h-4 w-4" />,
  account: <Wallet className="h-4 w-4" />
};

const statusConfig: Record<StreamStatus, { color: string; icon: React.ReactNode }> = {
  connected: { color: 'bg-emerald-500', icon: <Wifi className="h-3 w-3" /> },
  disconnected: { color: 'bg-muted', icon: <WifiOff className="h-3 w-3" /> },
  connecting: { color: 'bg-amber-500', icon: <Loader2 className="h-3 w-3 animate-spin" /> },
  error: { color: 'bg-destructive', icon: <AlertCircle className="h-3 w-3" /> },
  paused: { color: 'bg-blue-500', icon: <Pause className="h-3 w-3" /> }
};

const formatUptime = (connectedAt: Date | null) => {
  if (!connectedAt) return '-';
  return formatDistanceToNow(connectedAt, { addSuffix: false });
};

export const DataStreamPanel = () => {
  const { streams, pauseStream, resumeStream, reconnectStream, unregisterStream } = useDataStreams();
  const { getExchangeById } = useExchanges();

  return (
    <div className="space-y-3">
      {streams.map(stream => {
        const status = statusConfig[stream.status];
        const exchange = getExchangeById(stream.exchange);

        return (
          <Card key={stream.id} className="relative overflow-hidden">
            <div className={`absolute top-0 left-0 w-1 h-full ${status.color}`} />
            <CardContent className="p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-muted">
                    {streamTypeIcons[stream.type]}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="font-medium">{stream.name}</h4>
                      <Badge variant="outline" className="text-xs">
                        {exchange?.displayName || stream.exchange}
                      </Badge>
                      {stream.isReal && (
                        <Badge variant="secondary" className="text-xs bg-emerald-500/10 text-emerald-600 border-emerald-500/30">
                          LIVE
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {stream.symbols.slice(0, 5).join(', ')}
                      {stream.symbols.length > 5 && ` +${stream.symbols.length - 5} more`}
                    </p>
                    {stream.url && (
                      <p className="text-xs text-muted-foreground font-mono truncate max-w-[200px]">
                        {stream.url}
                      </p>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-1">
                  {stream.status === 'connected' ? (
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => pauseStream(stream.id)}>
                      <Pause className="h-3.5 w-3.5" />
                    </Button>
                  ) : stream.status === 'paused' ? (
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => resumeStream(stream.id)}>
                      <Play className="h-3.5 w-3.5" />
                    </Button>
                  ) : null}
                  <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => reconnectStream(stream.id)}>
                    <RefreshCw className="h-3.5 w-3.5" />
                  </Button>
                  <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive" onClick={() => unregisterStream(stream.id)}>
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>

              <div className="grid grid-cols-4 gap-4 mt-4 pt-3 border-t">
                <div>
                  <span className="text-xs text-muted-foreground">Messages/sec</span>
                  <p className="font-mono font-semibold text-sm">{stream.messagesPerSecond}</p>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Latency</span>
                  <p className="font-mono font-semibold text-sm">{stream.latencyMs}ms</p>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Errors</span>
                  <p className={`font-mono font-semibold text-sm ${stream.errorCount > 0 ? 'text-destructive' : ''}`}>
                    {stream.errorCount}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Uptime</span>
                  <p className="font-mono font-semibold text-sm">{formatUptime(stream.connectedAt)}</p>
                </div>
              </div>

              {stream.lastError && (
                <div className="mt-2 px-2 py-1.5 bg-destructive/10 rounded text-xs text-destructive">
                  Last error: {stream.lastError}
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
};
