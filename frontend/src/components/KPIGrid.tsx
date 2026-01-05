import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { TrendingUp, TrendingDown, Activity, BarChart3, AlertCircle, Zap, Target } from "lucide-react";

interface SnapshotData {
  symbol: string;
  last_price: number;
  last_price_change: number;
  last_price_change_pct: number;
  timestamp: string;
  trend_bias: string;
  vwap: number;
  vwap_position_pct: number;
  trend_strength_score: number;
  rvol: number;
  rsi_14: number;
  rsi_zone: string;
  macd_state: string;
  macd: number;
  macd_signal: number;
  macd_hist: number;
  atr_14: number;
  atr_pct: number;
  volatility_regime: string;
  bb_state: string;
  bb_width_pct: number;
  distance_prev_high_pct: number;
  distance_prev_low_pct: number;
  opening_range_status: string;
  premarket_context: string;
  day_bias: string;
  setup_quality_score: number;
}

interface KPIGridProps {
  data: SnapshotData | null;
  loading: boolean;
}

export const KPIGrid = ({ data, loading }: KPIGridProps) => {
  if (loading || !data) {
    return (
      <div className="space-y-6">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="space-y-3">
            <div className="h-4 bg-muted rounded w-32 animate-pulse" />
            <div className="grid grid-cols-3 gap-4">
              {[...Array(3)].map((_, j) => (
                <Card key={j} className="p-4 animate-pulse">
                  <div className="h-3 bg-muted rounded w-20 mb-3" />
                  <div className="h-7 bg-muted rounded" />
                </Card>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  const getBiasColor = (bias: string) => {
    if (bias.toLowerCase().includes("bullish") || bias.toLowerCase().includes("bull")) return "bull";
    if (bias.toLowerCase().includes("bearish") || bias.toLowerCase().includes("bear")) return "bear";
    return "neutral";
  };

  const getTrendStrengthLabel = (score: number) => {
    if (score >= 70) return "Strong";
    if (score >= 40) return "Moderate";
    return "Weak";
  };

  const getVolatilityColor = (regime: string) => {
    if (regime.toLowerCase().includes("high")) return "text-warning";
    if (regime.toLowerCase().includes("low")) return "text-info";
    return "text-muted-foreground";
  };

  return (
    <div className="space-y-6">
      {/* Composite Cluster */}
      <div>
        <h3 className="text-xs font-semibold text-muted-foreground mb-3 uppercase tracking-wider">Composite Overview</h3>
        <div className="grid grid-cols-2 gap-4">
          {/* Day Bias Card */}
          <Card className={`p-5 border-2 ${
            data.day_bias.toLowerCase().includes("bullish") 
              ? "bg-bull/5 border-bull/30" 
              : data.day_bias.toLowerCase().includes("bearish") 
              ? "bg-bear/5 border-bear/30" 
              : "bg-muted/30 border-border"
          }`}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Day Bias</span>
              {data.day_bias.toLowerCase().includes("bullish") ? (
                <TrendingUp className="h-5 w-5 text-bull" />
              ) : data.day_bias.toLowerCase().includes("bearish") ? (
                <TrendingDown className="h-5 w-5 text-bear" />
              ) : (
                <Activity className="h-5 w-5 text-neutral" />
              )}
            </div>
            <div className={`text-3xl font-bold ${getBiasColor(data.day_bias)}-text`}>
              {data.day_bias}
            </div>
          </Card>

          {/* Setup Quality Card */}
          <Card className="p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Setup Quality</span>
              <Target className="h-5 w-5 text-muted-foreground" />
            </div>
            <div className="space-y-2">
              <div className={`text-3xl font-bold number-mono ${
                data.setup_quality_score >= 70 ? "bull-text" : 
                data.setup_quality_score >= 40 ? "text-warning" : "bear-text"
              }`}>
                {data.setup_quality_score}
                <span className="text-lg text-muted-foreground ml-1">/100</span>
              </div>
              <Progress value={data.setup_quality_score} className="h-2" />
            </div>
          </Card>
        </div>
      </div>

      {/* Trend Cluster */}
      <div>
        <h3 className="text-xs font-semibold text-muted-foreground mb-3 uppercase tracking-wider">Trend Analysis</h3>
        <div className="grid grid-cols-3 gap-4">
          {/* Trend Bias */}
          <Card className="p-4">
            <div className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wide">Trend Bias</div>
            <Badge className={`${getBiasColor(data.trend_bias) === "bull" ? "bg-bull text-bull-foreground" : "bg-bear text-bear-foreground"} text-sm px-3 py-1`}>
              {data.trend_bias}
            </Badge>
          </Card>

          {/* VWAP Position */}
          <Card className="p-4">
            <div className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">VWAP Position</div>
            <div className={`text-lg font-bold number-mono ${data.vwap_position_pct >= 0 ? "bull-text" : "bear-text"}`}>
              {data.vwap_position_pct >= 0 ? "+" : ""}{data.vwap_position_pct.toFixed(2)}%
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              VWAP: ${data.vwap.toFixed(2)}
            </div>
          </Card>

          {/* Trend Strength */}
          <Card className="p-4">
            <div className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">Trend Strength</div>
            <div className="flex items-baseline gap-2">
              <span className={`text-lg font-bold number-mono ${
                data.trend_strength_score >= 70 ? "bull-text" : 
                data.trend_strength_score >= 40 ? "text-warning" : "bear-text"
              }`}>
                {data.trend_strength_score}
              </span>
              <span className="text-sm text-muted-foreground">
                {getTrendStrengthLabel(data.trend_strength_score)}
              </span>
            </div>
          </Card>
        </div>
      </div>

      {/* Momentum & Liquidity Cluster */}
      <div>
        <h3 className="text-xs font-semibold text-muted-foreground mb-3 uppercase tracking-wider">Momentum & Liquidity</h3>
        <div className="grid grid-cols-3 gap-4">
          {/* RVOL */}
          <Card className={`p-4 ${data.rvol >= 2.0 ? "border-2 border-warning/50 bg-warning/5" : ""}`}>
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Relative Volume</div>
              {data.rvol >= 2.0 && <Zap className="h-4 w-4 text-warning" />}
            </div>
            <div className="text-xl font-bold number-mono text-foreground">
              {data.rvol.toFixed(1)}×
            </div>
            <div className="text-xs text-muted-foreground mt-1">vs intraday avg</div>
          </Card>

          {/* RSI Zone */}
          <Card className="p-4">
            <div className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">RSI Zone</div>
            <Badge variant={
              data.rsi_zone.toLowerCase().includes("overbought") ? "destructive" :
              data.rsi_zone.toLowerCase().includes("oversold") ? "destructive" :
              "secondary"
            } className="text-sm">
              {data.rsi_zone}
            </Badge>
            <div className="text-xs text-muted-foreground mt-2">
              RSI(14): {data.rsi_14}
            </div>
          </Card>

          {/* MACD Momentum */}
          <Card className="p-4">
            <div className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">MACD Momentum</div>
            <Badge className={`${getBiasColor(data.macd_state) === "bull" ? "bg-bull text-bull-foreground" : "bg-bear text-bear-foreground"} text-sm`}>
              {data.macd_state}
            </Badge>
            <div className="text-xs text-muted-foreground mt-2">
              Hist: {data.macd_hist >= 0 ? "+" : ""}{data.macd_hist.toFixed(2)}
            </div>
          </Card>
        </div>
      </div>

      {/* Volatility Cluster */}
      <div>
        <h3 className="text-xs font-semibold text-muted-foreground mb-3 uppercase tracking-wider">Volatility</h3>
        <div className="grid grid-cols-3 gap-4">
          {/* Volatility Regime */}
          <Card className="p-4">
            <div className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">Volatility Regime</div>
            <div className={`text-lg font-bold ${getVolatilityColor(data.volatility_regime)}`}>
              {data.volatility_regime}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              ATR%: {data.atr_pct.toFixed(2)}%
            </div>
          </Card>

          {/* ATR Stop Guide */}
          <Card className="p-4">
            <div className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">ATR Stop Guide</div>
            <div className="space-y-1 text-xs number-mono">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Tight (0.5×):</span>
                <span className="font-semibold">${(data.atr_14 * 0.5).toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Standard (1×):</span>
                <span className="font-semibold">${data.atr_14.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Loose (1.5×):</span>
                <span className="font-semibold">${(data.atr_14 * 1.5).toFixed(2)}</span>
              </div>
            </div>
          </Card>

          {/* Bollinger State */}
          <Card className="p-4">
            <div className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">Bollinger State</div>
            <div className="text-lg font-bold text-foreground">{data.bb_state}</div>
            <div className="text-xs text-muted-foreground mt-1">
              Width: {data.bb_width_pct.toFixed(1)}%
            </div>
          </Card>
        </div>
      </div>

      {/* Structure & Levels Cluster */}
      <div>
        <h3 className="text-xs font-semibold text-muted-foreground mb-3 uppercase tracking-wider">Structure & Levels</h3>
        <div className="grid grid-cols-3 gap-4">
          {/* Range vs Yesterday */}
          <Card className="p-4">
            <div className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">Range vs Yesterday</div>
            <div className="space-y-1.5">
              <div className="flex justify-between items-center text-xs">
                <span className="text-muted-foreground">To Prev High:</span>
                <span className="font-semibold number-mono text-bear">
                  {data.distance_prev_high_pct.toFixed(1)}%
                </span>
              </div>
              <div className="flex justify-between items-center text-xs">
                <span className="text-muted-foreground">To Prev Low:</span>
                <span className="font-semibold number-mono text-bull">
                  {data.distance_prev_low_pct.toFixed(1)}%
                </span>
              </div>
            </div>
          </Card>

          {/* Opening Range Status */}
          <Card className="p-4">
            <div className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">Opening Range</div>
            <Badge variant="outline" className="text-xs">
              {data.opening_range_status}
            </Badge>
          </Card>

          {/* Premarket Context */}
          <Card className="p-4">
            <div className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">Premarket Context</div>
            <div className="text-sm font-medium text-foreground">
              {data.premarket_context}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};
