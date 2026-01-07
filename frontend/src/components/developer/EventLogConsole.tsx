import { useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  Clock,
  Copy,
  Database,
  Download,
  Filter,
  Pause,
  Play,
  Terminal,
  Trash2,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { useToast } from '@/hooks/use-toast';
import { clearLogs, LogLevel, LogSource, persistenceStore, useEventLogs, usePersistenceStatus } from '@/lib/eventLogStore';

const levelColors: Record<LogLevel, string> = {
  info: 'bg-blue-500/10 text-blue-600',
  warn: 'bg-amber-500/10 text-amber-600',
  error: 'bg-destructive/10 text-destructive',
  debug: 'bg-muted text-muted-foreground',
};

const sourceColors: Record<LogSource, string> = {
  supabase: 'text-emerald-600',
  alpaca: 'text-amber-600',
  exchange: 'text-blue-600',
  system: 'text-purple-600',
  ui: 'text-slate-600',
};

type TimeRange = '15m' | '1h' | '24h' | 'all';

export const EventLogConsole = () => {
  const logs = useEventLogs();
  const persistenceStatus = usePersistenceStatus();
  const { toast } = useToast();

  const [isPaused, setIsPaused] = useState(false);
  const [filter, setFilter] = useState('');
  const [levelFilter, setLevelFilter] = useState<LogLevel | 'all'>('all');
  const [sourceFilter, setSourceFilter] = useState<LogSource | 'all'>('all');
  const [timeRange, setTimeRange] = useState<TimeRange>('all');
  const [showTokenDialog, setShowTokenDialog] = useState(false);
  const [tokenInput, setTokenInput] = useState('');

  const scrollRef = useRef<HTMLDivElement>(null);
  const [pausedLogs, setPausedLogs] = useState(logs);

  useEffect(() => {
    if (!isPaused) setPausedLogs(logs);
  }, [logs, isPaused]);

  useEffect(() => {
    if (!isPaused && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [pausedLogs, isPaused]);

  const displayLogs = isPaused ? pausedLogs : logs;

  const getTimeFilteredLogs = () => {
    if (timeRange === 'all') return displayLogs;

    const now = Date.now();
    const ranges: Record<TimeRange, number> = {
      '15m': 15 * 60 * 1000,
      '1h': 60 * 60 * 1000,
      '24h': 24 * 60 * 60 * 1000,
      all: Number.POSITIVE_INFINITY,
    };

    const cutoff = now - ranges[timeRange];
    return displayLogs.filter((log) => log.timestamp.getTime() >= cutoff);
  };

  const filteredLogs = getTimeFilteredLogs().filter((log) => {
    if (levelFilter !== 'all' && log.level !== levelFilter) return false;
    if (sourceFilter !== 'all' && log.source !== sourceFilter) return false;
    if (!filter) return true;

    const searchLower = filter.toLowerCase();
    return (
      log.message.toLowerCase().includes(searchLower) ||
      log.source.toLowerCase().includes(searchLower) ||
      log.category.toLowerCase().includes(searchLower)
    );
  });

  const copyLogs = (count?: number) => {
    const logsToCopy = count ? filteredLogs.slice(-count) : filteredLogs;
    const text = logsToCopy
      .map(
        (log) =>
          `[${log.timestamp.toISOString()}] [${log.level.toUpperCase()}] [${log.source}] [${log.category}] ${log.message}${
            log.meta ? ` ${JSON.stringify(log.meta)}` : ''
          }`
      )
      .join('\n');

    navigator.clipboard.writeText(text);
    toast({ title: 'Copied to clipboard', description: `${logsToCopy.length} log entries copied` });
  };

  const exportJson = () => {
    const exportData = filteredLogs.map((log) => ({
      timestamp: log.timestamp.toISOString(),
      level: log.level,
      source: log.source,
      category: log.category,
      message: log.message,
      meta: log.meta,
    }));

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `dev-logs-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`;
    a.click();
    URL.revokeObjectURL(url);

    toast({ title: 'Logs exported', description: `${filteredLogs.length} entries exported to JSON` });
  };

  const handlePersistToggle = (checked: boolean) => {
    if (checked) {
      const storedToken = persistenceStore.getStoredToken();
      if (storedToken) {
        persistenceStore.togglePersistence(true, storedToken);
      } else {
        setShowTokenDialog(true);
      }
    } else {
      persistenceStore.togglePersistence(false);
    }
  };

  const handleTokenSubmit = () => {
    if (!tokenInput.trim()) return;
    persistenceStore.togglePersistence(true, tokenInput.trim());
    setShowTokenDialog(false);
    setTokenInput('');
    toast({
      title: 'Log persistence enabled',
      description: 'Logs will be flushed periodically when an ingest URL is configured.',
    });
  };

  const formatTime = (date: Date) => {
    return `${date.toLocaleTimeString()}.${date.getMilliseconds().toString().padStart(3, '0')}`;
  };

  const formatFlushTime = () => {
    if (!persistenceStatus.lastFlushTime) return null;
    const seconds = Math.floor((Date.now() - persistenceStatus.lastFlushTime.getTime()) / 1000);
    return `${seconds}s ago`;
  };

  return (
    <>
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Terminal className="h-4 w-4" />
              Event Log Console
              <Badge variant="outline" className="ml-2 text-xs">
                {filteredLogs.length} / {displayLogs.length}
              </Badge>
            </CardTitle>

            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-muted/50">
                <Database className="h-4 w-4 text-muted-foreground" />
                <Label htmlFor="persist-toggle" className="text-xs font-medium cursor-pointer">
                  Persist
                </Label>
                <Switch id="persist-toggle" checked={persistenceStatus.enabled} onCheckedChange={handlePersistToggle} />
                {persistenceStatus.enabled && (
                  <div className="flex items-center gap-1.5 text-xs">
                    {persistenceStatus.lastError ? (
                      <span className="text-destructive flex items-center gap-1">
                        <AlertCircle className="h-3 w-3" />
                        Error
                      </span>
                    ) : (
                      <>
                        <Clock className="h-3 w-3 text-muted-foreground" />
                        <span className="text-muted-foreground">{formatFlushTime() || 'Waiting...'}</span>
                        {persistenceStatus.pendingCount > 0 && (
                          <Badge variant="secondary" className="text-[10px] px-1 py-0">
                            {persistenceStatus.pendingCount}
                          </Badge>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2">
                <Button variant={isPaused ? 'default' : 'outline'} size="sm" onClick={() => setIsPaused(!isPaused)}>
                  {isPaused ? <Play className="h-3 w-3 mr-1" /> : <Pause className="h-3 w-3 mr-1" />}
                  {isPaused ? 'Resume' : 'Pause'}
                </Button>
                <Button variant="outline" size="sm" onClick={() => copyLogs()}>
                  <Copy className="h-3 w-3 mr-1" />
                  Copy
                </Button>
                <Button variant="outline" size="sm" onClick={clearLogs}>
                  <Trash2 className="h-3 w-3 mr-1" />
                  Clear
                </Button>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 mt-3 flex-wrap">
            <div className="relative flex-1 min-w-[200px]">
              <Filter className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input placeholder="Filter logs..." value={filter} onChange={(e) => setFilter(e.target.value)} className="pl-8 h-9" />
            </div>

            <Select value={timeRange} onValueChange={(v: TimeRange) => setTimeRange(v)}>
              <SelectTrigger className="w-[100px] h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="15m">Last 15m</SelectItem>
                <SelectItem value="1h">Last 1h</SelectItem>
                <SelectItem value="24h">Last 24h</SelectItem>
                <SelectItem value="all">All Time</SelectItem>
              </SelectContent>
            </Select>

            <div className="flex gap-1">
              {(['all', 'supabase', 'alpaca', 'exchange', 'system', 'ui'] as const).map((source) => (
                <Button
                  key={source}
                  variant={sourceFilter === source ? 'default' : 'outline'}
                  size="sm"
                  className="text-xs h-9 px-2.5"
                  onClick={() => setSourceFilter(source)}
                >
                  {source === 'all' ? 'All' : source.charAt(0).toUpperCase() + source.slice(1)}
                </Button>
              ))}
            </div>

            <div className="flex gap-1">
              {(['all', 'info', 'warn', 'error', 'debug'] as const).map((level) => (
                <Button
                  key={level}
                  variant={levelFilter === level ? 'default' : 'outline'}
                  size="sm"
                  className="text-xs h-9 px-2.5"
                  onClick={() => setLevelFilter(level)}
                >
                  {level === 'all' ? 'All' : level.charAt(0).toUpperCase() + level.slice(1)}
                </Button>
              ))}
            </div>

            <div className="flex gap-1 ml-auto">
              <Button variant="outline" size="sm" className="h-9" onClick={exportJson}>
                <Download className="h-3 w-3 mr-1" />
                Export JSON
              </Button>
              <Button variant="outline" size="sm" className="h-9" onClick={() => copyLogs(200)}>
                <Copy className="h-3 w-3 mr-1" />
                Copy Last 200
              </Button>
            </div>
          </div>
        </CardHeader>

        <CardContent>
          <ScrollArea className="h-80 rounded-md border bg-muted/30" ref={scrollRef}>
            <div className="p-2 font-mono text-xs space-y-1">
              {filteredLogs.length === 0 ? (
                <div className="text-muted-foreground text-center py-8">
                  {displayLogs.length === 0
                    ? 'No events logged yet.'
                    : 'No logs match the current filters'}
                </div>
              ) : (
                filteredLogs.map((log) => (
                  <div key={log.id} className="flex items-start gap-2 py-0.5 hover:bg-muted/50 rounded px-1">
                    <span className="text-muted-foreground whitespace-nowrap">{formatTime(log.timestamp)}</span>
                    <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${levelColors[log.level]}`}>
                      {log.level.toUpperCase()}
                    </Badge>
                    <span className={`whitespace-nowrap font-medium ${sourceColors[log.source]}`}>[{log.source}]</span>
                    <span className="text-muted-foreground whitespace-nowrap">[{log.category}]</span>
                    <span className="text-foreground flex-1">{log.message}</span>
                    {log.meta && Object.keys(log.meta).length > 0 && (
                      <span className="text-muted-foreground text-[10px]">{JSON.stringify(log.meta)}</span>
                    )}
                  </div>
                ))
              )}
            </div>
          </ScrollArea>
        </CardContent>
      </Card>

      <Dialog open={showTokenDialog} onOpenChange={setShowTokenDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Enable Log Persistence</DialogTitle>
            <DialogDescription>
              Enter your OPS token. To actually flush logs, also configure an ingest URL via
              <span className="font-mono"> window.__OPS_LOG_INGEST_URL__ </span>
              or localStorage key <span className="font-mono">ops_log_ingest_url</span>.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Label htmlFor="ops-token">OPS Token</Label>
            <Input
              id="ops-token"
              type="password"
              placeholder="Enter your token..."
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              className="mt-2"
              onKeyDown={(e) => e.key === 'Enter' && handleTokenSubmit()}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowTokenDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleTokenSubmit} disabled={!tokenInput.trim()}>
              Enable Persistence
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};

