import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { useDataStreams } from '@/contexts/DataStreamContext';
import { 
  RefreshCw, Pause, Play, Trash2, Download, Settings, 
  Loader2, CheckCircle, XCircle
} from 'lucide-react';
import { toast } from 'sonner';

export const SystemControls = () => {
  const { reconnectAll, pauseAll, resumeAll, streams } = useDataStreams();
  const [mockMode, setMockMode] = useState(true);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [isPausing, setIsPausing] = useState(false);
  
  const allPaused = streams.every(s => s.status === 'paused');

  const handleReconnectAll = async () => {
    setIsReconnecting(true);
    reconnectAll();
    await new Promise(resolve => setTimeout(resolve, 2000));
    setIsReconnecting(false);
    toast.success('All streams reconnected', {
      description: `${streams.length} streams reconnected successfully`
    });
  };

  const handlePauseResumeAll = async () => {
    setIsPausing(true);
    if (allPaused) {
      resumeAll();
      toast.info('All streams resumed');
    } else {
      pauseAll();
      toast.info('All streams paused');
    }
    await new Promise(resolve => setTimeout(resolve, 500));
    setIsPausing(false);
  };

  const handleClearCache = () => {
    localStorage.clear();
    sessionStorage.clear();
    toast.success('Cache cleared', {
      description: 'Local and session storage cleared'
    });
  };

  const handleDownloadReport = () => {
    const report = {
      timestamp: new Date().toISOString(),
      streams: streams.map(s => ({
        id: s.id,
        name: s.name,
        status: s.status,
        latencyMs: s.latencyMs,
        messagesPerSecond: s.messagesPerSecond,
        errorCount: s.errorCount
      })),
      mockMode
    };

    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `system-report-${new Date().toISOString().split('T')[0]}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success('Report downloaded');
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Settings className="h-4 w-4" />
          System Controls
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Button 
            onClick={handleReconnectAll} 
            disabled={isReconnecting}
            variant="outline"
            className="justify-start"
          >
            {isReconnecting ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4 mr-2" />
            )}
            Reconnect All
          </Button>

          <Button 
            onClick={handlePauseResumeAll}
            disabled={isPausing}
            variant="outline"
            className="justify-start"
          >
            {isPausing ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : allPaused ? (
              <Play className="h-4 w-4 mr-2" />
            ) : (
              <Pause className="h-4 w-4 mr-2" />
            )}
            {allPaused ? 'Resume All' : 'Pause All'}
          </Button>

          <Button onClick={handleClearCache} variant="outline" className="justify-start">
            <Trash2 className="h-4 w-4 mr-2" />
            Clear Cache
          </Button>

          <Button onClick={handleDownloadReport} variant="outline" className="justify-start">
            <Download className="h-4 w-4 mr-2" />
            Download Report
          </Button>
        </div>

        <div className="pt-3 border-t">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="mock-mode" className="text-sm font-medium">Mock Data Mode</Label>
              <p className="text-xs text-muted-foreground">
                Use simulated data instead of live connections
              </p>
            </div>
            <Switch
              id="mock-mode"
              checked={mockMode}
              onCheckedChange={setMockMode}
            />
          </div>
        </div>

        <div className="pt-3 border-t">
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-1.5">
              <CheckCircle className="h-4 w-4 text-emerald-500" />
              <span>{streams.filter(s => s.status === 'connected').length} Connected</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Pause className="h-4 w-4 text-blue-500" />
              <span>{streams.filter(s => s.status === 'paused').length} Paused</span>
            </div>
            <div className="flex items-center gap-1.5">
              <XCircle className="h-4 w-4 text-destructive" />
              <span>{streams.filter(s => s.status === 'error').length} Errors</span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
