import { useState, useMemo, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { WatchlistTower } from "@/components/f1/WatchlistTower";
import { TelemetryChart } from "@/components/f1/TelemetryChart";
import { BattleStation } from "@/components/f1/BattleStation";
import { RadioFeed } from "@/components/f1/RadioFeed";
import { VitalsBar } from "@/components/f1/VitalsBar";
import { IndicatorStrip } from "@/components/f1/IndicatorStrip";
import { DashboardHeader } from "@/components/DashboardHeader";
import { OptionsChain } from "@/components/OptionsChain";
import { useLayout } from "@/contexts/LayoutContext";
import { useLiveWatchlist } from "@/hooks/useLiveWatchlist";
import { useLiveQuotes } from "@/hooks/useLiveQuotes";
import LiveQuotesWidget from "@/components/LiveQuotesWidget";
import { useLiveAccount } from "@/hooks/useLiveAccount";

const F1Dashboard = () => {
  const navigate = useNavigate();
  const [currentSymbol, setCurrentSymbol] = useState("SPY");
  const [secondSymbol, setSecondSymbol] = useState("QQQ");
  const [splitMode, setSplitMode] = useState(false);
  const { layout } = useLayout();
  const {
    watchlist,
    loading: watchlistLoading,
    isLive,
    status: feedStatus,
    heartbeatAt,
    hasLiveQuotes,
  } = useLiveWatchlist();

  const { equity, buying_power, cash, loading: accountLoading, hasCache } = useLiveAccount();
  
  // Get live prices for current symbols from the watchlist
  const primaryPrice = useMemo(() => watchlist.find(item => item.symbol === currentSymbol) || {
    symbol: currentSymbol, price: 0, change: 0, changePct: 0, volume: 0, status: "normal", sparklineData: [], isLive: false
  }, [watchlist, currentSymbol]);
  const secondaryPrice = useMemo(() => watchlist.find(item => item.symbol === secondSymbol) || {
    symbol: secondSymbol, price: 0, change: 0, changePct: 0, volume: 0, status: "normal", sparklineData: [], isLive: false
  }, [watchlist, secondSymbol]);

  // Dynamic snapshot data for indicator cards
  const [snapshotData, setSnapshotData] = useState({
    rsi_14: 64,
    rsi_zone: "Bullish",
    macd_state: "Bullish",
    rvol: 1.8,
    trend_bias: "Bullish",
    volatility_regime: "Normal",
  });

  // Simulate real-time data updates every 3-5 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      setSnapshotData((prev) => {
        // Simulate RSI fluctuation
        const rsiDelta = (Math.random() - 0.5) * 8;
        const newRSI = Math.max(30, Math.min(85, prev.rsi_14 + rsiDelta));
        
        let rsiZone = "Neutral";
        if (newRSI >= 70) rsiZone = "Overbought";
        else if (newRSI >= 55) rsiZone = "Bullish";
        else if (newRSI <= 30) rsiZone = "Oversold";
        else if (newRSI <= 45) rsiZone = "Bearish";

        // Simulate MACD state changes
        const macdRoll = Math.random();
        let macdState = prev.macd_state;
        if (macdRoll < 0.15) macdState = "Bullish";
        else if (macdRoll < 0.3) macdState = "Bearish";
        else if (macdRoll < 0.45) macdState = "Neutral";

        // Simulate RVOL spikes
        const rvolDelta = (Math.random() - 0.5) * 0.4;
        const newRVOL = Math.max(0.5, Math.min(3.5, prev.rvol + rvolDelta));

        // Simulate trend bias
        const trendRoll = Math.random();
        let trendBias = prev.trend_bias;
        if (trendRoll < 0.2) trendBias = "Bullish";
        else if (trendRoll < 0.4) trendBias = "Bearish";
        else if (trendRoll < 0.6) trendBias = "Neutral";

        let volRegime = "Normal";
        if (newRVOL > 2.5) volRegime = "High";
        else if (newRVOL < 1) volRegime = "Low";

        return {
          rsi_14: Math.round(newRSI),
          rsi_zone: rsiZone,
          macd_state: macdState,
          rvol: newRVOL,
          trend_bias: trendBias,
        };
      });
    }, Math.random() * 2000 + 3000); // Random interval 3-5 seconds

    return () => clearInterval(interval);
  }, []);

  const handleOpenConsole = (symbol: string) => {
    navigate(`/console/${symbol}`);
  };

  // Account data (warm-cache + live snapshot via `useLiveAccount`)
  const accountData = useMemo(() => {
    const safeEquity = typeof equity === "number" && Number.isFinite(equity) ? equity : 0;
    const safeBuyingPower = typeof buying_power === "number" && Number.isFinite(buying_power) ? buying_power : 0;
    const safeCash = typeof cash === "number" && Number.isFinite(cash) ? cash : 0;
    return {
      equity: safeEquity,
      dayPnl: 0,
      dayPnlPct: 0,
      buyingPower: safeBuyingPower,
      cash: safeCash,
      // Avoid divide-by-zero in the gauge.
      maxBuyingPower: Math.max(safeBuyingPower, 1),
    };
  }, [equity, buying_power, cash]);

  // Chart data - use live prices if available, fallback to mock
  const chartData = {
    symbol: currentSymbol,
    currentPrice: primaryPrice.isLive ? primaryPrice.price : 432.15,
    change: primaryPrice.isLive ? primaryPrice.change : 1.23,
    changePct: primaryPrice.isLive ? primaryPrice.changePct : 0.29,
    openPnL: 165.00,
    positionSize: 10,
    isLive: primaryPrice.isLive,
  };

  const secondChartData = {
    symbol: secondSymbol,
    currentPrice: secondaryPrice.isLive ? secondaryPrice.price : 389.50,
    change: secondaryPrice.isLive ? secondaryPrice.change : -0.85,
    changePct: secondaryPrice.isLive ? secondaryPrice.changePct : -0.22,
    openPnL: -45.00,
    positionSize: 5,
    isLive: secondaryPrice.isLive,
  };

  // Dynamic grid layout based on visible components
  const gridClasses = useMemo(() => {
    const hasWatchlist = layout.showWatchlist;
    const hasBattle = layout.showBattleStation;
    const hasRadio = layout.showRadioFeed;
    
    if (!hasWatchlist && !hasBattle && !hasRadio) return "grid-cols-1";
    if (!hasWatchlist && !hasBattle) return "grid-cols-10";
    if (!hasWatchlist && !hasRadio) return "grid-cols-10";
    if (!hasWatchlist) return "grid-cols-10";
    if (!hasBattle && !hasRadio) return "grid-cols-9";
    return "grid-cols-12";
  }, [layout.showWatchlist, layout.showBattleStation, layout.showRadioFeed]);

  const telemetryColSpan = useMemo(() => {
    const hasWatchlist = layout.showWatchlist;
    const hasRight = layout.showBattleStation || layout.showRadioFeed;
    
    if (!hasWatchlist && !hasRight) return "col-span-1";
    if (!hasWatchlist) return "col-span-7";
    if (!hasRight) return "col-span-10";
    return "col-span-7";
  }, [layout.showWatchlist, layout.showBattleStation, layout.showRadioFeed]);

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <DashboardHeader
        currentSymbol={currentSymbol}
        onSymbolChange={setCurrentSymbol}
        environment="production"
        equity={accountData.equity}
        dayPnl={accountData.dayPnl}
        dayPnlPct={accountData.dayPnlPct}
        splitMode={splitMode}
        onSplitModeToggle={() => setSplitMode(!splitMode)}
        secondSymbol={secondSymbol}
        onSecondSymbolChange={setSecondSymbol}
      />

      {/* Top Bar - Vitals */}
      {layout.showVitalsBar && (
        <div className="px-4 pt-4 animate-fade-in">
          <VitalsBar
            equity={accountData.equity}
            buyingPower={accountData.buyingPower}
            maxBuyingPower={accountData.maxBuyingPower}
            cash={accountData.cash}
            dayPnl={accountData.dayPnl}
            dayPnlPct={accountData.dayPnlPct}
            loading={accountLoading && !hasCache}
          />
        </div>
      )}

      {/* Indicator Strip */}
      {layout.showIndicatorStrip && (
        <div className="animate-fade-in">
          <IndicatorStrip snapshotData={snapshotData} />
        </div>
      )}

      {/* Main Grid Layout */}
      <div className={`flex-1 grid ${gridClasses} gap-4 p-4 overflow-hidden transition-all duration-300 ease-in-out`}>
        {/* Left Sidebar - Watchlist Tower (2 cols) */}
        {layout.showWatchlist && (
          <div className="col-span-2 animate-fade-in">
            <WatchlistTower 
              items={watchlist}
              loading={watchlistLoading}
              isLive={isLive}
              feedStatus={feedStatus}
              heartbeatAt={heartbeatAt}
              hasLiveQuotes={hasLiveQuotes}
              onSymbolClick={setCurrentSymbol}
              onSymbolDoubleClick={handleOpenConsole}
            />
          </div>
        )}

        {/* Center - Telemetry Chart (dynamic cols) */}
        {layout.showTelemetry && (
          <div className={`${telemetryColSpan} animate-fade-in transition-all duration-300`}>
            {splitMode ? (
              <div className="grid grid-cols-2 gap-4 h-full">
                <TelemetryChart 
                  symbol={chartData.symbol}
                  currentPrice={chartData.currentPrice}
                  change={chartData.change}
                  changePct={chartData.changePct}
                  openPnL={chartData.openPnL}
                  positionSize={chartData.positionSize}
                  isLive={chartData.isLive}
                  onOpenConsole={() => handleOpenConsole(chartData.symbol)}
                />
                <TelemetryChart 
                  symbol={secondChartData.symbol}
                  currentPrice={secondChartData.currentPrice}
                  change={secondChartData.change}
                  changePct={secondChartData.changePct}
                  openPnL={secondChartData.openPnL}
                  positionSize={secondChartData.positionSize}
                  isLive={secondChartData.isLive}
                  onOpenConsole={() => handleOpenConsole(secondChartData.symbol)}
                />
              </div>
            ) : (
              <TelemetryChart 
                symbol={chartData.symbol}
                currentPrice={chartData.currentPrice}
                change={chartData.change}
                changePct={chartData.changePct}
                openPnL={chartData.openPnL}
                positionSize={chartData.positionSize}
                isLive={chartData.isLive}
                onOpenConsole={() => handleOpenConsole(chartData.symbol)}
              />
            )}
          </div>
        )}

        {/* Right Panel - Battle Station + Radio Feed (3 cols) */}
        {(layout.showBattleStation || layout.showRadioFeed) && (
          <div className="col-span-3 space-y-4 animate-fade-in">
            {/* Battle Station - Top */}
            {layout.showBattleStation && (
              <div className={layout.showRadioFeed ? "h-[calc(50%-0.5rem)]" : "h-full"}>
                <BattleStation symbol={currentSymbol} />
              </div>
            )}

            {/* Radio Feed - Bottom */}
            {layout.showRadioFeed && (
              <div className={layout.showBattleStation ? "h-[calc(50%-0.5rem)]" : "h-full"}>
                <RadioFeed />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Live Quotes + System Status */}
      <div className="px-4 pb-4 animate-fade-in">
        <LiveQuotesWidget />
      </div>

      {/* Options Chain Panel - Collapsible section below main grid */}
      {layout.showOptionsChain && (
        <div className="px-4 pb-4 animate-fade-in">
          <OptionsChain symbol={currentSymbol} />
        </div>
      )}
    </div>
  );
};

export default F1Dashboard;
