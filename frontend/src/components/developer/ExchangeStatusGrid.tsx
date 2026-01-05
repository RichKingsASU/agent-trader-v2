import { useExchanges, ExchangeStatus, ExchangeType } from '@/contexts/ExchangeContext';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Activity, Server, TrendingUp, Wifi, WifiOff, AlertTriangle, Wrench, RefreshCw } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

const statusConfig: Record<ExchangeStatus, { color: string; icon: React.ReactNode; label: string }> = {
  active: { color: 'bg-emerald-500', icon: <Wifi className="h-3 w-3" />, label: 'Active' },
  inactive: { color: 'bg-muted', icon: <WifiOff className="h-3 w-3" />, label: 'Inactive' },
  degraded: { color: 'bg-amber-500', icon: <AlertTriangle className="h-3 w-3" />, label: 'Degraded' },
  maintenance: { color: 'bg-blue-500', icon: <Wrench className="h-3 w-3" />, label: 'Maintenance' }
};

const typeIcons: Record<ExchangeType, React.ReactNode> = {
  broker: <TrendingUp className="h-4 w-4" />,
  'data-provider': <Server className="h-4 w-4" />,
  'options-exchange': <Activity className="h-4 w-4" />
};

export const ExchangeStatusGrid = () => {
  const { exchanges, testConnection } = useExchanges();

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {exchanges.map(exchange => {
        const status = statusConfig[exchange.status];
        const rateLimitPercent = (exchange.rateLimits.requestsUsed / exchange.rateLimits.requestsPerMinute) * 100;

        return (
          <Card key={exchange.id} className="relative overflow-hidden">
            <div className={`absolute top-0 left-0 w-1 h-full ${status.color}`} />
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">{typeIcons[exchange.type]}</span>
                  <CardTitle className="text-base">{exchange.displayName}</CardTitle>
                </div>
                <Badge variant="outline" className="flex items-center gap-1 text-xs">
                  <span className={`h-2 w-2 rounded-full ${status.color}`} />
                  {status.label}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <span className="text-muted-foreground text-xs">Latency</span>
                  <p className="font-mono font-medium">{exchange.latencyMs.toFixed(0)}ms</p>
                </div>
                <div>
                  <span className="text-muted-foreground text-xs">API Version</span>
                  <p className="font-mono font-medium">{exchange.apiVersion}</p>
                </div>
              </div>

              <div>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-muted-foreground">Rate Limit</span>
                  <span className="font-mono">{exchange.rateLimits.requestsUsed}/{exchange.rateLimits.requestsPerMinute}</span>
                </div>
                <Progress 
                  value={rateLimitPercent} 
                  className={`h-1.5 ${rateLimitPercent > 80 ? '[&>div]:bg-amber-500' : ''}`}
                />
              </div>

              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">
                  Last check: {formatDistanceToNow(exchange.lastHealthCheck, { addSuffix: true })}
                </span>
                <div className="flex gap-1">
                  {exchange.capabilities.map(cap => (
                    <Badge key={cap} variant="secondary" className="text-[10px] px-1.5 py-0">
                      {cap}
                    </Badge>
                  ))}
                </div>
              </div>

              <div className="flex gap-2 pt-1">
                <Button 
                  variant="outline" 
                  size="sm" 
                  className="flex-1 text-xs h-7"
                  onClick={() => testConnection(exchange.id)}
                >
                  <RefreshCw className="h-3 w-3 mr-1" />
                  Test
                </Button>
                <Badge variant="outline" className="text-xs">
                  {exchange.streams.length} stream{exchange.streams.length !== 1 ? 's' : ''}
                </Badge>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
};
