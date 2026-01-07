import React, { useState, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { 
  Loader2, 
  AlertCircle, 
  TrendingUp, 
  TrendingDown, 
  Crown,
  Sparkles,
  Filter,
  Target,
  Zap,
  Activity
} from "lucide-react";
import { useWhaleFlow, type OptionsFlowTrade } from "@/hooks/useWhaleFlow";

interface WhaleFlowTrackerProps {
  maxTrades?: number;
}

type TradeWithGexSignal = OptionsFlowTrade & { gexSignal?: string | null };

export const WhaleFlowTracker: React.FC<WhaleFlowTrackerProps> = ({ maxTrades = 100 }) => {
  const { trades, systemStatus, loading, error } = useWhaleFlow(maxTrades);
  
  // Filter states
  const [aggressiveOnly, setAggressiveOnly] = useState(false);
  const [otmFocusOnly, setOtmFocusOnly] = useState(false);
  const [gexOverlay, setGexOverlay] = useState(true);

  // Calculate premium ratios
  const premiumStats = useMemo(() => {
    const bullishPremium = trades
      .filter(t => t.sentiment === "bullish")
      .reduce((sum, t) => sum + t.premium, 0);
    
    const bearishPremium = trades
      .filter(t => t.sentiment === "bearish")
      .reduce((sum, t) => sum + t.premium, 0);
    
    const totalPremium = bullishPremium + bearishPremium;
    const bullishRatio = totalPremium > 0 ? (bullishPremium / totalPremium) * 100 : 50;
    const bearishRatio = totalPremium > 0 ? (bearishPremium / totalPremium) * 100 : 50;

    return {
      bullishPremium,
      bearishPremium,
      totalPremium,
      bullishRatio,
      bearishRatio,
    };
  }, [trades]);

  // Apply filters
  const filteredTrades = useMemo(() => {
    let filtered = [...trades];

    // Aggressive Only: Only show trades at the Ask (buying pressure)
    if (aggressiveOnly) {
      filtered = filtered.filter(t => t.execution_side === "ask");
    }

    // OTM Focus: Only show significantly OTM trades (>5%)
    if (otmFocusOnly) {
      filtered = filtered.filter(t => t.moneyness === "OTM" && Math.abs(t.otm_percentage) > 5);
    }

    return filtered;
  }, [trades, aggressiveOnly, otmFocusOnly]);

  // GEX Overlay: Flag trades that match the GEX regime
  const tradesWithGexSignals = useMemo<TradeWithGexSignal[]>(() => {
    if (!gexOverlay || !systemStatus) return filteredTrades;

    return filteredTrades.map(trade => {
      let gexSignal: string | null = null;

      // If GEX is Negative (high volatility expected)
      if (systemStatus.volatility_bias === "Bearish") {
        // Flag aggressive Put buying as Volatility Expansion Signal
        if (trade.option_type === "put" && 
            trade.side === "buy" && 
            trade.execution_side === "ask") {
          gexSignal = "Volatility Expansion Signal";
        }
        // Flag aggressive Call selling
        if (trade.option_type === "call" && 
            trade.side === "sell" && 
            trade.execution_side === "bid") {
          gexSignal = "Bearish Conviction";
        }
      }

      // If GEX is Positive (low volatility expected)
      if (systemStatus.volatility_bias === "Bullish") {
        // Flag aggressive Call buying
        if (trade.option_type === "call" && 
            trade.side === "buy" && 
            trade.execution_side === "ask") {
          gexSignal = "Bullish Conviction";
        }
        // Flag Put selling (bullish bet on stability)
        if (trade.option_type === "put" && 
            trade.side === "sell") {
          gexSignal = "Premium Collection";
        }
      }

      return { ...trade, gexSignal };
    });
  }, [filteredTrades, gexOverlay, systemStatus]);

  if (loading) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Crown className="h-6 w-6 text-yellow-500" />
            Whale Flow Tracker
          </CardTitle>
          <CardDescription>Real-time institutional options flow</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-64 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Crown className="h-6 w-6 text-yellow-500" />
            Whale Flow Tracker
          </CardTitle>
          <CardDescription>Real-time institutional options flow</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-destructive">
            <AlertCircle className="h-5 w-5" />
            <span>{error}</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="w-full">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-2xl">
              <Crown className="h-6 w-6 text-yellow-500" />
              Whale Flow Tracker
            </CardTitle>
            <CardDescription>
              Real-time institutional options flow • {tradesWithGexSignals.length} trades tracked
            </CardDescription>
          </div>
          <Badge variant="outline" className="text-xs font-semibold">
            <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse mr-2" />
            LIVE
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* Heat Map Intensity Bar */}
        <div className="bg-muted/30 p-6 rounded-lg border border-border">
          <div className="flex items-center justify-between mb-4">
            <h4 className="font-semibold flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Premium Flow Heat Map
            </h4>
            <div className="text-sm text-muted-foreground">
              Total Premium: ${(premiumStats.totalPremium / 1_000_000).toFixed(2)}M
            </div>
          </div>

          {/* Heat Map Bar */}
          <div className="relative h-12 rounded-lg overflow-hidden border border-border">
            <div className="absolute inset-0 flex">
              {/* Bullish side */}
              <div
                className="bg-gradient-to-r from-emerald-500 to-emerald-600 flex items-center justify-center transition-all duration-500"
                style={{ width: `${premiumStats.bullishRatio}%` }}
              >
                {premiumStats.bullishRatio > 15 && (
                  <div className="text-white font-bold text-sm flex items-center gap-1">
                    <TrendingUp className="h-4 w-4" />
                    {premiumStats.bullishRatio.toFixed(1)}%
                  </div>
                )}
              </div>

              {/* Bearish side */}
              <div
                className="bg-gradient-to-l from-red-500 to-red-600 flex items-center justify-center transition-all duration-500"
                style={{ width: `${premiumStats.bearishRatio}%` }}
              >
                {premiumStats.bearishRatio > 15 && (
                  <div className="text-white font-bold text-sm flex items-center gap-1">
                    {premiumStats.bearishRatio.toFixed(1)}%
                    <TrendingDown className="h-4 w-4" />
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Legend */}
          <div className="grid grid-cols-2 gap-4 mt-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-emerald-500" />
                <span className="text-sm font-medium">Bullish Premium</span>
              </div>
              <span className="text-sm font-bold text-emerald-500">
                ${(premiumStats.bullishPremium / 1_000_000).toFixed(2)}M
              </span>
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-red-500" />
                <span className="text-sm font-medium">Bearish Premium</span>
              </div>
              <span className="text-sm font-bold text-red-500">
                ${(premiumStats.bearishPremium / 1_000_000).toFixed(2)}M
              </span>
            </div>
          </div>
        </div>

        {/* Smart Filters */}
        <div className="bg-muted/30 p-6 rounded-lg border border-border">
          <h4 className="font-semibold mb-4 flex items-center gap-2">
            <Filter className="h-4 w-4" />
            Smart Filters
          </h4>
          
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Aggressive Only */}
            <div className="flex items-center justify-between space-x-3">
              <div className="flex items-center gap-2 flex-1">
                <Zap className="h-4 w-4 text-orange-500" />
                <div>
                  <Label htmlFor="aggressive" className="text-sm font-medium cursor-pointer">
                    Aggressive Only
                  </Label>
                  <p className="text-xs text-muted-foreground">Trades at Ask (buying pressure)</p>
                </div>
              </div>
              <Switch
                id="aggressive"
                checked={aggressiveOnly}
                onCheckedChange={setAggressiveOnly}
              />
            </div>

            {/* OTM Focus */}
            <div className="flex items-center justify-between space-x-3">
              <div className="flex items-center gap-2 flex-1">
                <Target className="h-4 w-4 text-blue-500" />
                <div>
                  <Label htmlFor="otm" className="text-sm font-medium cursor-pointer">
                    OTM Focus
                  </Label>
                  <p className="text-xs text-muted-foreground">Show significantly OTM trades</p>
                </div>
              </div>
              <Switch
                id="otm"
                checked={otmFocusOnly}
                onCheckedChange={setOtmFocusOnly}
              />
            </div>

            {/* GEX Overlay */}
            <div className="flex items-center justify-between space-x-3">
              <div className="flex items-center gap-2 flex-1">
                <Sparkles className="h-4 w-4 text-purple-500" />
                <div>
                  <Label htmlFor="gex" className="text-sm font-medium cursor-pointer">
                    GEX Overlay
                  </Label>
                  <p className="text-xs text-muted-foreground">
                    Highlight flow matching regime
                    {systemStatus && ` (${systemStatus.volatility_bias})`}
                  </p>
                </div>
              </div>
              <Switch
                id="gex"
                checked={gexOverlay}
                onCheckedChange={setGexOverlay}
              />
            </div>
          </div>
        </div>

        {/* Options Flow Table */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h4 className="font-semibold">Live Options Flow</h4>
            <div className="flex items-center gap-4 text-xs text-muted-foreground">
              <div className="flex items-center gap-2">
                <Crown className="h-3.5 w-3.5 text-yellow-500" />
                <span>Golden Sweep (&gt;$1M, &lt;14 DTE)</span>
              </div>
              {gexOverlay && systemStatus && (
                <div className="flex items-center gap-2">
                  <Sparkles className="h-3.5 w-3.5 text-purple-500" />
                  <span>GEX Signal Active</span>
                </div>
              )}
            </div>
          </div>

          <ScrollArea className="h-[600px] pr-4">
            <div className="space-y-2">
              {tradesWithGexSignals.length === 0 ? (
                <div className="text-center py-12 text-muted-foreground">
                  <AlertCircle className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p>No trades match current filters</p>
                  <p className="text-sm mt-2">Try adjusting your filter settings</p>
                </div>
              ) : (
                tradesWithGexSignals.map((trade) => (
                  <Card
                    key={trade.id}
                    className={`p-4 border-l-4 transition-all hover:shadow-lg hover:scale-[1.01] cursor-pointer ${
                      trade.is_golden_sweep
                        ? "border-l-yellow-500 bg-yellow-500/10 shadow-yellow-500/20"
                        : trade.sentiment === "bullish"
                        ? "border-l-emerald-500 bg-emerald-500/5"
                        : "border-l-red-500 bg-red-500/5"
                    }`}
                  >
                    <div className="grid grid-cols-12 gap-4 items-center">
                      {/* Golden Sweep Icon */}
                      <div className="col-span-1 flex justify-center">
                        {trade.is_golden_sweep ? (
                          <Crown className="h-5 w-5 text-yellow-500 animate-pulse" />
                        ) : trade.sentiment === "bullish" ? (
                          <TrendingUp className="h-5 w-5 text-emerald-500" />
                        ) : (
                          <TrendingDown className="h-5 w-5 text-red-500" />
                        )}
                      </div>

                      {/* Time */}
                      <div className="col-span-1">
                        <div className="text-xs text-muted-foreground">Time</div>
                        <div className="text-sm font-mono font-semibold">
                          {trade.timestamp ? trade.timestamp.toLocaleTimeString() : "—"}
                        </div>
                      </div>

                      {/* Contract Details */}
                      <div className="col-span-3">
                        <div className="text-xs text-muted-foreground">Contract</div>
                        <div className="text-sm font-semibold">
                          {trade.symbol} ${trade.strike} {trade.option_type.toUpperCase()} {trade.expiry}
                        </div>
                        <div className="text-xs text-muted-foreground mt-0.5">
                          {trade.days_to_expiry} DTE • {trade.moneyness} 
                          {trade.moneyness === "OTM" && ` (${Math.abs(trade.otm_percentage).toFixed(1)}%)`}
                        </div>
                      </div>

                      {/* Side & Execution */}
                      <div className="col-span-1">
                        <div className="text-xs text-muted-foreground">Side</div>
                        <Badge
                          variant={trade.side === "buy" ? "default" : "secondary"}
                          className={
                            trade.side === "buy"
                              ? "bg-emerald-500 hover:bg-emerald-600"
                              : "bg-red-500 hover:bg-red-600"
                          }
                        >
                          {trade.side.toUpperCase()}
                        </Badge>
                        {trade.execution_side === "ask" && (
                          <div className="text-xs text-orange-500 font-semibold mt-1">@ ASK</div>
                        )}
                      </div>

                      {/* Size */}
                      <div className="col-span-1">
                        <div className="text-xs text-muted-foreground">Size</div>
                        <div className="text-sm font-mono font-semibold">{trade.size}</div>
                      </div>

                      {/* Premium */}
                      <div className="col-span-2">
                        <div className="text-xs text-muted-foreground">Premium</div>
                        <div className="text-sm font-mono font-bold text-primary">
                          ${trade.premium >= 1_000_000
                            ? `${(trade.premium / 1_000_000).toFixed(2)}M`
                            : `${(trade.premium / 1_000).toFixed(1)}k`}
                        </div>
                        {trade.is_golden_sweep && (
                          <div className="text-xs text-yellow-500 font-semibold mt-0.5">
                            GOLDEN SWEEP
                          </div>
                        )}
                      </div>

                      {/* Greeks */}
                      <div className="col-span-1">
                        <div className="text-xs text-muted-foreground">IV</div>
                        <div className="text-sm font-bold">
                          {(trade.iv * 100).toFixed(0)}%
                        </div>
                        <div className="text-xs text-muted-foreground mt-0.5">
                          Δ {trade.delta.toFixed(2)}
                        </div>
                      </div>

                      {/* GEX Signal */}
                      <div className="col-span-2">
                        {trade.gexSignal ? (
                          <div className="flex items-center gap-1">
                            <Sparkles className="h-3.5 w-3.5 text-purple-500" />
                            <span className="text-xs font-semibold text-purple-500">
                              {trade.gexSignal}
                            </span>
                          </div>
                        ) : (
                          <Badge
                            variant="outline"
                            className={`text-xs ${
                              trade.sentiment === "bullish"
                                ? "text-emerald-500"
                                : trade.sentiment === "bearish"
                                ? "text-red-500"
                                : ""
                            }`}
                          >
                            {trade.sentiment.toUpperCase()}
                          </Badge>
                        )}
                      </div>
                    </div>
                  </Card>
                ))
              )}
            </div>
          </ScrollArea>
        </div>
      </CardContent>
    </Card>
  );
};
