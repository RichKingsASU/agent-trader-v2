import { useState } from "react";
import { DashboardHeader } from "@/components/DashboardHeader";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { OptionsChain } from "@/components/OptionsChain";
import { GreeksHeatmap } from "@/components/options/GreeksHeatmap";
import { UnusualActivityScanner } from "@/components/options/UnusualActivityScanner";
import { MultiExpiryComparison } from "@/components/options/MultiExpiryComparison";
import { useLiveQuotes } from "@/hooks/useLiveQuotes";

const Options = () => {
  const [currentSymbol, setCurrentSymbol] = useState("SPY");

  const { equity } = useLiveQuotes();

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <DashboardHeader
        currentSymbol={currentSymbol}
        onSymbolChange={setCurrentSymbol}
        environment="production"
        equity={equity}
        dayPnl={0}
        dayPnlPct={0}
      />

      {/* Main Content */}
      <div className="flex-1 p-6">
        <div className="mb-6">
          <h2 className="text-2xl font-bold tracking-tight mb-1">Options Analysis Center</h2>
          <p className="text-sm text-muted-foreground">
            Deep-dive options analytics, Greeks visualization, and flow detection for {currentSymbol}
          </p>
        </div>

        <Tabs defaultValue="chain" className="w-full">
          <TabsList className="mb-4">
            <TabsTrigger value="chain">Options Chain</TabsTrigger>
            <TabsTrigger value="comparison">Multi-Expiry Comparison</TabsTrigger>
            <TabsTrigger value="greeks">Greeks Heatmap</TabsTrigger>
            <TabsTrigger value="activity">Unusual Activity</TabsTrigger>
          </TabsList>

          <TabsContent value="chain" className="mt-0">
            <OptionsChain symbol={currentSymbol} />
          </TabsContent>

          <TabsContent value="comparison" className="mt-0">
            <MultiExpiryComparison symbol={currentSymbol} />
          </TabsContent>

          <TabsContent value="greeks" className="mt-0">
            <GreeksHeatmap symbol={currentSymbol} />
          </TabsContent>

          <TabsContent value="activity" className="mt-0">
            <UnusualActivityScanner symbol={currentSymbol} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
};

export default Options;
