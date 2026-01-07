import { Activity, Radio, Terminal } from 'lucide-react';

import { ExchangeProvider } from '@/contexts/ExchangeContext';
import { DataStreamProvider } from '@/contexts/DataStreamContext';
import { AlpacaStreamManager } from '@/components/developer/AlpacaStreamManager';
import { DataFreshnessGrid } from '@/components/developer/DataFreshnessGrid';
import { EventLogConsole } from '@/components/developer/EventLogConsole';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

export default function OpsDebug() {
  return (
    <DataStreamProvider>
      <ExchangeProvider>
        <div className="flex flex-col h-full p-6 space-y-6 overflow-auto">
          <div>
            <h1 className="text-2xl font-bold">Ops Debug</h1>
            <p className="text-sm text-muted-foreground">Local diagnostic tools (safe to use without backend).</p>
          </div>

          <Tabs defaultValue="streams" className="space-y-6">
            <TabsList>
              <TabsTrigger value="streams" className="flex items-center gap-2">
                <Radio className="h-4 w-4" />
                Streams
              </TabsTrigger>
              <TabsTrigger value="freshness" className="flex items-center gap-2">
                <Activity className="h-4 w-4" />
                Freshness
              </TabsTrigger>
              <TabsTrigger value="logs" className="flex items-center gap-2">
                <Terminal className="h-4 w-4" />
                Logs
              </TabsTrigger>
            </TabsList>

            <TabsContent value="streams" className="space-y-4">
              <AlpacaStreamManager />
            </TabsContent>

            <TabsContent value="freshness" className="space-y-4">
              <DataFreshnessGrid />
            </TabsContent>

            <TabsContent value="logs" className="space-y-4">
              <EventLogConsole />
            </TabsContent>
          </Tabs>
        </div>
      </ExchangeProvider>
    </DataStreamProvider>
  );
}

