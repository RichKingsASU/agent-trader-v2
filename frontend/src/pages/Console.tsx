import { useState, useEffect, useCallback } from "react";
import { useParams } from "react-router-dom";
import { getFirestore, onSnapshot } from "firebase/firestore";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConsoleHeader } from "@/components/ConsoleHeader";
import { StructureMap } from "@/components/console/StructureMap";
import { ExecutionChart } from "@/components/console/ExecutionChart";
import { DecisionStrip } from "@/components/console/DecisionStrip";
import { FlowMomentum } from "@/components/console/FlowMomentum";
import { ConsolePositionCard } from "@/components/console/ConsolePositionCard";
import { MicroNotes } from "@/components/console/MicroNotes";
import { TradeHistoryTable } from "@/components/console/TradeHistoryTable";
import { TrailingStopControl } from "@/components/expert/TrailingStopControl";
import { LiquidityKpi } from "@/components/expert/LiquidityKpi";
import { PerformanceKpi } from "@/components/expert/PerformanceKpi";
import { PerformanceChart } from "@/components/expert/PerformanceChart";
import { RiskCalculator } from "@/components/expert/RiskCalculator";
import { OptionChainSelector } from "@/components/expert/OptionChainSelector";
import { OrderEntryPanel } from "@/components/expert/OrderEntryPanel";
import { BattlegroundMode } from "@/components/expert/BattlegroundMode";
import { Skeleton } from "@/components/ui/skeleton";
import { useTrailingStopAutomation } from "@/hooks/useTrailingStopAutomation";
import { useToast } from "@/hooks/use-toast";
import { StopLossConfig } from "@/utils/stopCalculations";
import { useAuth } from "@/contexts/AuthContext";
import { tenantDoc } from "@/lib/tenancy/firestore";
import { useMarketLiveQuotes } from "@/hooks/useMarketLiveQuotes";

const Console = () => {
  const { symbol = "SPY" } = useParams<{ symbol: string }>();
  const { toast } = useToast();
  const { tenantId } = useAuth();
  const { status: ingestStatus, heartbeatAt } = useMarketLiveQuotes({ subscribeQuotes: false });
  const [snapshotData, setSnapshotData] = useState<any>(null);
  const [levelsData, setLevelsData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [trailingStopEnabled, setTrailingStopEnabled] = useState(false);
  const [stopConfig, setStopConfig] = useState<StopLossConfig>({
    type: 'trailing',
    trailingDistance: 1.5,
    trailingUnit: 'atr',
  });
  const [selectedOptionContract, setSelectedOptionContract] = useState<any>(null);
  const [calculatedPositionSize, setCalculatedPositionSize] = useState<number>(0);
  const [battlegroundOpen, setBattlegroundOpen] = useState(false);
  const [battlegroundLevel, setBattlegroundLevel] = useState(236.50);
  const [battleSessions, setBattleSessions] = useState<any[]>([]);

  useEffect(() => {
    setLoading(true);
    const db = getFirestore();
    if (!tenantId) return;
    const docRef = tenantDoc(db, tenantId, "live_quotes", symbol.toUpperCase());

    const unsubscribe = onSnapshot(docRef, (docSnap) => {
      if (docSnap.exists()) {
        const data = docSnap.data();
        setSnapshotData(data);
        setLastUpdate(new Date());
      } else {
        console.warn(`No live data for symbol: ${symbol}`);
      }
      setLoading(false);
    });

    return () => unsubscribe();
  }, [symbol, tenantId]);

  // Mock position for trailing stop automation
  const mockPosition = {
    symbol: symbol,
    side: 'long' as const,
    entryPrice: 430.50,
    currentPrice: snapshotData?.last_trade_price || 0,
    quantity: 100,
  };

  // Trailing stop automation
  const { currentStopLevel, distance } = useTrailingStopAutomation({
    position: mockPosition,
    config: stopConfig,
    enabled: trailingStopEnabled,
    atrValue: snapshotData?.atr_14,
  });

  const currentTime = new Date();
  const hour = currentTime.getHours();
  const session = hour < 9 || (hour === 9 && currentTime.getMinutes() < 30) 
    ? "Pre-Market" 
    : hour >= 16 
    ? "After-Hours" 
    : "Regular";

  return (
    <div className="min-h-screen bg-background">
      {/* Console Header with Navigation */}
      <ConsoleHeader
        symbol={symbol}
        companyName={snapshotData?.company_name}
        lastPrice={snapshotData?.last_trade_price}
        priceChange={snapshotData?.last_trade_price_change}
        priceChangePct={snapshotData?.last_trade_price_change_pct}
        dayBias={snapshotData?.day_bias}
        session={session}
        connected={ingestStatus === "LIVE" && !loading}
        lastUpdate={lastUpdate}
        loading={loading}
        ingestStatus={ingestStatus}
        heartbeatAt={heartbeatAt}
      />

      {/* 3-Column Layout */}
      <div className="p-4">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Left Column - Structure Map & Expert Controls */}
          <div className="lg:col-span-3 space-y-4">
            <StructureMap 
              snapshotData={snapshotData} 
              levelsData={levelsData} 
              loading={loading} 
            />
            
            <Button 
              onClick={() => setBattlegroundOpen(true)}
              className="w-full"
              variant="outline"
              size="lg"
            >
              ⚔️ Engage Battleground Mode
            </Button>
            
            {/* Expert Trader Modules */}
            <LiquidityKpi 
              rvol={snapshotData?.rvol}
              ticksPerMinute={350}
              avgTicksPerMinute={120}
              tradesPerMinute={45}
              loading={loading}
            />
            
            <PerformanceKpi 
              winRate={72}
              avgRR={2.3}
              edge={0.34}
              totalTrades={50}
              loading={loading}
            />
            
            <PerformanceChart loading={loading} />
            
            <RiskCalculator 
              symbol={symbol}
              currentPrice={snapshotData?.last_trade_price}
              atrValue={snapshotData?.atr_14}
              loading={loading}
              selectedOption={selectedOptionContract}
              onCalculate={(results) => setCalculatedPositionSize(results.positionSize)}
            />
            
            <OptionChainSelector
              symbol={symbol}
              currentPrice={snapshotData?.last_trade_price}
              loading={loading}
              onSelect={(contract) => {
                setSelectedOptionContract(contract);
              }}
            />
            
            <OrderEntryPanel
              symbol={symbol}
              selectedOption={selectedOptionContract}
              calculatedSize={calculatedPositionSize}
              loading={loading}
            />
          </div>

          {/* Center Column - Execution Chart + Decision Strip */}
          <div className="lg:col-span-6 space-y-4">
            <ExecutionChart 
              symbol={symbol}
              levelsData={levelsData} 
              currentPrice={snapshotData?.last_trade_price}
              vwap={snapshotData?.vwap}
              atr={snapshotData?.atr_14}
              loading={loading}
            />
            
            <DecisionStrip 
              snapshotData={snapshotData}
              levelsData={levelsData}
              loading={loading}
            />
          </div>

          {/* Right Column - Flow & Position */}
          <div className="lg:col-span-3 space-y-4">
            <FlowMomentum 
              snapshotData={snapshotData} 
              loading={loading} 
            />
            
            <ConsolePositionCard 
              symbol={symbol}
              currentPrice={snapshotData?.last_trade_price}
              levelsData={levelsData}
              loading={loading}
            />
            
            {/* Trailing Stop Control */}
            <TrailingStopControl 
              position={mockPosition}
              atrValue={snapshotData?.atr_14}
              onApply={(config) => {
                setStopConfig(config);
                setTrailingStopEnabled(true);
              }}
            />
            
            {trailingStopEnabled && (
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm font-semibold">Live Stop Monitor</CardTitle>
                    <Badge variant="outline" className="bg-primary/10 text-primary border-primary/20">
                      Active
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">Current Stop:</span>
                    <span className="font-mono font-semibold text-foreground">
                      ${currentStopLevel.toFixed(2)}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">Distance:</span>
                    <span className="font-mono text-foreground">
                      {distance.percent.toFixed(2)}% / {distance.atr?.toFixed(2)} ATR
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-muted-foreground">Risk ($):</span>
                    <span className="font-mono text-foreground">
                      ${distance.dollars.toFixed(2)}
                    </span>
                  </div>
                </CardContent>
              </Card>
            )}
            
            <MicroNotes 
              defaultSymbol={symbol}
            />
          </div>
        </div>
      </div>

      {/* Bottom Section - Trade History */}
      <div className="p-6">
        <TradeHistoryTable symbol={symbol} />
      </div>

      {/* Battleground Mode Dialog */}
      <BattlegroundMode 
        open={battlegroundOpen}
        onOpenChange={setBattlegroundOpen}
        symbol={symbol}
        priceLevel={battlegroundLevel}
        currentPrice={snapshotData?.last_trade_price || 0}
        sessions={battleSessions}
        onSessionComplete={(session) => setBattleSessions(prev => [...prev, session])}
      />
    </div>
  );
};

export default Console;
