import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ArrowLeft, Activity, Server, Radio, Terminal, Settings, History } from 'lucide-react';
import { DataStreamProvider, useDataStreams } from '@/contexts/DataStreamContext';
import { ExchangeProvider, useExchanges } from '@/contexts/ExchangeContext';
import { ExchangeStatusGrid } from '@/components/developer/ExchangeStatusGrid';
import { DataStreamPanel } from '@/components/developer/DataStreamPanel';

import { StreamMetricsChart } from '@/components/developer/StreamMetricsChart';


import { SystemControls } from '@/components/developer/SystemControls';
import { StreamManager } from '@/components/developer/StreamManager';
import LiveQuotesWidget from '@/components/test/LiveQuotesWidget';

const DeveloperHeader = () => {
  const dataStreamContext = useDataStreams();
  const exchangeContext = useExchanges();
  
  const streamStats = dataStreamContext.getAggregateStats();
  const exchangeHealth = exchangeContext.getOverallHealth();

  const getHealthIndicator = () => {
    if (streamStats.errors > 0 || exchangeHealth.down > 0) return 'bg-destructive';
    if (exchangeHealth.degraded > 0) return 'bg-amber-500';
    return 'bg-emerald-500';
  };

  return (
    <header className="border-b bg-card">
      <div className="container mx-auto px-4 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="sm" asChild>
              <Link to="/">
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back
              </Link>
            </Button>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold">Developer Console</h1>
              <span className={`h-2.5 w-2.5 rounded-full ${getHealthIndicator()} animate-pulse`} />
            </div>
          </div>
          <div className="flex items-center gap-4 text-sm text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <Server className="h-4 w-4" />
              <span>{exchangeHealth.healthy} Exchanges</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Radio className="h-4 w-4" />
              <span>{streamStats.connected}/{streamStats.totalStreams} Streams</span>
            </div>
            <div className="flex items-center gap-1.5">
              <Activity className="h-4 w-4" />
              <span>{streamStats.totalMps} msg/s</span>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
};

const DeveloperContent = () => {
  return (
    <div className="container mx-auto px-4 py-6">
      <Tabs defaultValue="overview" className="space-y-6">
        <TabsList>
          <TabsTrigger value="overview" className="flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Overview
          </TabsTrigger>
          <TabsTrigger value="exchanges" className="flex items-center gap-2">
            <Server className="h-4 w-4" />
            Exchanges
          </TabsTrigger>
          <TabsTrigger value="streams" className="flex items-center gap-2">
            <Radio className="h-4 w-4" />
            Data Streams
          </TabsTrigger>
          <TabsTrigger value="debug" className="flex items-center gap-2">
            <Terminal className="h-4 w-4" />
            Debug Console
          </TabsTrigger>
          <TabsTrigger value="history" className="flex items-center gap-2">
            <History className="h-4 w-4" />
            Log History
          </TabsTrigger>
          <TabsTrigger value="controls" className="flex items-center gap-2">
            <Settings className="h-4 w-4" />
            Controls
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <div className="grid lg:grid-cols-2 gap-6">
            <StreamMetricsChart />
            <LiveQuotesWidget />
          </div>
          
        </TabsContent>

        <TabsContent value="exchanges" className="space-y-6">
          <ExchangeStatusGrid />
        </TabsContent>

        <TabsContent value="streams" className="space-y-6">
          <div className="grid md:grid-cols-2 gap-4">
            <StreamManager />
          </div>
          <DataStreamPanel />
        </TabsContent>

        <TabsContent value="debug" className="space-y-6">
          
        </TabsContent>

        <TabsContent value="history" className="space-y-6">
          
        </TabsContent>

        <TabsContent value="controls" className="space-y-6">
          <div className="grid md:grid-cols-2 gap-6">
            <SystemControls />
            <StreamManager />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
};

const Developer = () => {
  return (
    <DataStreamProvider>
      <ExchangeProvider>
        <div className="min-h-screen bg-background">
          <DeveloperHeader />
          <DeveloperContent />
        </div>
      </ExchangeProvider>
    </DataStreamProvider>
  );
};

export default Developer;
