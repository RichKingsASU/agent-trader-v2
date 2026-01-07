import { useMemo, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { DashboardHeader } from "@/components/DashboardHeader";
import { AccountPanel } from "@/components/AccountPanel";
import { ChartHUD } from "@/components/ChartHUD";
import { BotStatusPanel } from "@/components/BotStatusPanel";
import { KPIGrid } from "@/components/KPIGrid";
import { TradingViewChart } from "@/components/TradingViewChart";
import { OptionsChain } from "@/components/OptionsChain";
import { OptionsPositionsTable } from "@/components/OptionsPositionsTable";
import { OptionsOrderTicket } from "@/components/OptionsOrderTicket";
import { NewsAlertsPanel } from "@/components/NewsAlertsPanel";
import { TraderNotesWidget } from "@/components/TraderNotesWidget";
import { TradeHistoryTable } from "@/components/TradeHistoryTable";
import { EquityChart } from "@/components/EquityChart";
import { SystemPulse } from "@/components/SystemPulse";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Target, ChevronDown, ChevronUp } from "lucide-react";
import { toast } from "sonner";
import { useLayout } from "@/contexts/LayoutContext";
import { useLiveAccount } from "@/hooks/useLiveAccount";

interface AccountData {
  account_id: string;
  environment: "production" | "sandbox";
  market: string;
  equity: number;
  day_pnl: number;
  day_pnl_pct: number;
  unrealized_pnl: number;
  realized_pnl: number;
  settled_cash: number;
  buying_power: number;
  margin_available: number;
  portfolio_delta: number;
  portfolio_theta: number;
  portfolio_vega: number;
}

interface BotStatusData {
  status: "in_trade" | "flat";
  current_symbol?: string;
  current_side?: "long" | "short";
  entry_price?: number;
  current_price?: number;
  position_size?: number;
  pnl_open?: number;
}

type SnapshotData = Record<string, unknown>;

const Index = () => {
  const navigate = useNavigate();
  const { layout } = useLayout();
  const [currentSymbol, setCurrentSymbol] = useState("SPY");
  const [accountData, setAccountData] = useState<AccountData | null>(null);
  const [botStatus, setBotStatus] = useState<BotStatusData | null>(null);
  const [snapshotData, setSnapshotData] = useState<SnapshotData | null>(null);
  const [botControls, setBotControls] = useState({
    bot_enabled: true,
    buying_enabled: true,
    selling_enabled: true,
  });
  const [newsPanelOpen, setNewsPanelOpen] = useState(true);
  const [notesPanelOpen, setNotesPanelOpen] = useState(true);
  const { equity, buyingPower, cash } = useLiveAccount();

  const effectiveAccountData = useMemo(() => {
    if (!accountData) return null;
    return {
      ...accountData,
      equity: equity !== 0 ? equity : accountData.equity,
      buying_power: buyingPower !== 0 ? buyingPower : accountData.buying_power,
      settled_cash: cash !== 0 ? cash : accountData.settled_cash,
    };
  }, [accountData, buyingPower, cash, equity]);

  // Mock data fetching - replace with actual API calls
  useEffect(() => {
    // Mock account data
    setAccountData({
      account_id: "XYZ123",
      environment: "production" as const,
      market: "US Equities & Options",
      equity,
      day_pnl: 650.75,
      day_pnl_pct: 0.52,
      unrealized_pnl: 300.10,
      realized_pnl: 350.65,
      settled_cash: 40000.0,
      buying_power: buyingPower,
      margin_available: 150000.00,
      portfolio_delta: 35.2,
      portfolio_theta: -18.5,
      portfolio_vega: 42.3,
    });

    // Mock bot status
    setBotStatus({
      status: "in_trade" as const,
      current_symbol: "SPY",
      current_side: "long" as const,
      entry_price: 430.50,
      current_price: 432.15,
      position_size: 10,
      pnl_open: 165.00,
    });

    // Mock snapshot data
    setSnapshotData({
      symbol: currentSymbol,
      last_price: 432.15,
      last_price_change: 1.23,
      last_price_change_pct: 0.29,
      timestamp: new Date().toISOString(),
      trend_bias: "Bullish",
      vwap: 430.80,
      vwap_position_pct: 0.31,
      trend_strength_score: 82,
      rvol: 2.8,
      rsi_14: 64,
      rsi_zone: "Bullish",
      macd_state: "Bullish",
      macd: 0.45,
      macd_signal: 0.33,
      macd_hist: 0.12,
      atr_14: 1.25,
      atr_pct: 0.85,
      volatility_regime: "High",
      bb_state: "Expanded",
      bb_width_pct: 3.1,
      distance_prev_high_pct: 1.8,
      distance_prev_low_pct: 3.4,
      opening_range_status: "Above ORH",
      premarket_context: "Trading above PM High",
      day_bias: "Bullish",
      setup_quality_score: 78,
    });
  }, [currentSymbol, equity, buyingPower]);

  const handleSymbolChange = (symbol: string) => {
    setCurrentSymbol(symbol);
    toast.info(`Switched to ${symbol}`);
  };

  const handleControlChange = (controls: typeof botControls) => {
    setBotControls(controls);
    toast.success("Bot controls updated");
    // TODO: POST to /api/bot/set_controls
  };

  const handlePanic = () => {
    toast.error("PANIC EXECUTED - All positions liquidated");
    setBotStatus({ status: "flat" as const });
    setBotControls({
      bot_enabled: false,
      buying_enabled: false,
      selling_enabled: false,
    });
    // TODO: POST to /api/bot/panic
  };

  const handleOpenConsole = () => {
    navigate(`/console/${currentSymbol}`);
  };

  return (
    <div className="min-h-screen bg-background">
      <DashboardHeader
        currentSymbol={currentSymbol}
        onSymbolChange={handleSymbolChange}
        environment={accountData?.environment || "production"}
        equity={equity}
        dayPnl={accountData?.day_pnl || 0}
        dayPnlPct={accountData?.day_pnl_pct || 0}
      />

      <div className="p-4 space-y-4">
        {/* Top Row - Title and Controls */}
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide ui-label neon-glow-blue">Market Overview</h2>
          <Button onClick={handleOpenConsole} size="sm" variant="outline" className="glass-subtle hover:glass-card transition-all">
            <Target className="h-4 w-4 mr-2" />
            Open Decision Console
          </Button>
        </div>

        {/* System Health & Equity Row */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <EquityChart />
          </div>
          <div>
            <SystemPulse />
          </div>
        </div>

        {/* Middle Row - Chart & Controls */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 transition-all duration-300">
          {/* Chart & Options Section - Dynamic width based on sidebar visibility */}
          <div className={`transition-all duration-300 ${
            layout.showAccountPanel || layout.showBotStatus || layout.showOptionsPositions || 
            layout.showOrderTicket || layout.showNews || layout.showNotes 
              ? "lg:col-span-2" 
              : "lg:col-span-3"
          }`}>
            <Tabs defaultValue="chart" className="w-full">
              <TabsList className="w-full justify-start mb-4 glass-subtle">
                <TabsTrigger value="chart" className="flex-1 max-w-[120px]">Chart</TabsTrigger>
                {layout.showKPIs && <TabsTrigger value="kpis" className="flex-1 max-w-[120px]">KPIs</TabsTrigger>}
                {layout.showOptionsChain && <TabsTrigger value="options" className="flex-1 max-w-[150px]">Options Chain</TabsTrigger>}
              </TabsList>
              
              <TabsContent value="chart" className="mt-0 relative">
                <div className="glass-card">
                  <ChartHUD 
                    controls={botControls}
                    onControlChange={handleControlChange}
                    onPanic={handlePanic}
                    botStatus={botStatus?.status || "flat"}
                  />
                  <TradingViewChart symbol={currentSymbol} />
                </div>
              </TabsContent>
              
              {layout.showKPIs && (
                <TabsContent value="kpis" className="mt-0">
                  <Card className="glass-card p-6">
                    <KPIGrid data={snapshotData} loading={!snapshotData} />
                  </Card>
                </TabsContent>
              )}
              
              {layout.showOptionsChain && (
                <TabsContent value="options" className="mt-0">
                  <div className="glass-card">
                    <OptionsChain symbol={currentSymbol} />
                  </div>
                </TabsContent>
              )}
            </Tabs>
          </div>

          {/* Command & Status Column - Conditionally rendered */}
          {(layout.showAccountPanel || layout.showBotStatus || layout.showOptionsPositions || 
            layout.showOrderTicket || layout.showNews || layout.showNotes) && (
            <div className="space-y-4 transition-all duration-300 animate-fade-in">
              {layout.showAccountPanel && (
                <div className="transition-all duration-300 animate-fade-in">
                  <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label neon-glow-blue">Account & Risk</h3>
                  <div className="glass-card p-4">
                    <AccountPanel data={effectiveAccountData} loading={false} />
                  </div>
                </div>
              )}

              {layout.showOptionsPositions && (
                <div className="transition-all duration-300 animate-fade-in">
                  <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">Options Positions</h3>
                  <div className="glass-card">
                    <OptionsPositionsTable />
                  </div>
                </div>
              )}
              
              {layout.showBotStatus && (
                <div className="transition-all duration-300 animate-fade-in">
                  <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">Bot Status</h3>
                  <div className="glass-card p-4">
                    <BotStatusPanel data={botStatus} loading={false} />
                  </div>
                </div>
              )}

              {layout.showOrderTicket && (
                <div className="transition-all duration-300 animate-fade-in">
                  <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">Options Order Ticket</h3>
                  <div className="glass-card">
                    <OptionsOrderTicket defaultSymbol={currentSymbol} />
                  </div>
                </div>
              )}

              {/* Collapsible News Panel */}
              {layout.showNews && (
                <Collapsible open={newsPanelOpen} onOpenChange={setNewsPanelOpen} className="transition-all duration-300 animate-fade-in">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider ui-label">News & Alerts</h3>
                    <CollapsibleTrigger asChild>
                      <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                        {newsPanelOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                      </Button>
                    </CollapsibleTrigger>
                  </div>
                  <CollapsibleContent>
                    <NewsAlertsPanel />
                  </CollapsibleContent>
                </Collapsible>
              )}

              {/* Collapsible Notes Panel */}
              {layout.showNotes && (
                <Collapsible open={notesPanelOpen} onOpenChange={setNotesPanelOpen} className="transition-all duration-300 animate-fade-in">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider ui-label">Trader Notes</h3>
                    <CollapsibleTrigger asChild>
                      <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                        {notesPanelOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                      </Button>
                    </CollapsibleTrigger>
                  </div>
                  <CollapsibleContent>
                    <TraderNotesWidget defaultSymbol={currentSymbol} />
                  </CollapsibleContent>
                </Collapsible>
              )}
            </div>
          )}
        </div>

        {/* Bottom - Trade History */}
        {layout.showTradeHistory && (
          <div className="transition-all duration-300 animate-fade-in">
            <h3 className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wide ui-label">Trade History</h3>
            <div className="glass-card">
              <TradeHistoryTable />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default Index;
