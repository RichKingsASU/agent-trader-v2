import { Badge } from "@/components/ui/badge";
import { Gauge, TrendingUp, Activity, BarChart3, Zap } from "lucide-react";

interface IndicatorStripProps {
  snapshotData: {
    rsi_14: number;
    rsi_zone: string;
    macd_state: string;
    rvol: number;
    trend_bias: string;
    volatility_regime: string;
  } | null;
}

export const IndicatorStrip = ({ snapshotData }: IndicatorStripProps) => {
  if (!snapshotData) return null;

  const isHighVolume = snapshotData.rvol >= 2.0;
  const isExtreme = snapshotData.rsi_zone === "Overbought" || snapshotData.rsi_zone === "Oversold";

  // Color determination functions
  const getRSIColor = (zone: string) => {
    if (zone === "Overbought" || zone === "Oversold") return "bg-bear/20 border-bear text-bear";
    if (zone === "Bullish") return "bg-bull/20 border-bull text-bull";
    if (zone === "Bearish") return "bg-bear/20 border-bear text-bear";
    return "bg-muted border-border text-muted-foreground";
  };

  const getMACDColor = (state: string) => {
    if (state === "Bullish") return "bg-bull/20 border-bull text-bull";
    if (state === "Bearish") return "bg-bear/20 border-bear text-bear";
    return "bg-muted border-border text-muted-foreground";
  };

  const getRVOLColor = (rvol: number) => {
    if (rvol >= 2.0) return "bg-warning/20 border-warning text-warning animate-pulse";
    if (rvol >= 1.5) return "bg-warning/10 border-warning/50 text-warning";
    return "bg-muted border-border text-muted-foreground";
  };

  const getTrendColor = (bias: string) => {
    if (bias === "Bullish") return "bg-bull/20 border-bull text-bull";
    if (bias === "Bearish") return "bg-bear/20 border-bear text-bear";
    return "bg-muted border-border text-muted-foreground";
  };

  const getVolatilityColor = (regime: string) => {
    if (regime === "High") return "bg-warning/20 border-warning text-warning";
    if (regime === "Low") return "bg-info/20 border-info text-info";
    return "bg-muted border-border text-muted-foreground";
  };

  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-card/50 backdrop-blur-sm border-y border-border">
      {/* RSI Zone */}
      <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition-all duration-300 ${getRSIColor(snapshotData.rsi_zone)} ${isExtreme ? 'shadow-lg' : ''}`}>
        <Gauge className="h-4 w-4" />
        <div className="flex flex-col">
          <span className="text-[10px] font-medium opacity-70">RSI ZONE</span>
          <span className="text-sm font-bold">{snapshotData.rsi_zone}</span>
          <span className="text-xs opacity-60 number-mono">({snapshotData.rsi_14})</span>
        </div>
      </div>

      {/* MACD State */}
      <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition-all duration-300 ${getMACDColor(snapshotData.macd_state)}`}>
        <TrendingUp className="h-4 w-4" />
        <div className="flex flex-col">
          <span className="text-[10px] font-medium opacity-70">MACD</span>
          <span className="text-sm font-bold">{snapshotData.macd_state}</span>
          {snapshotData.macd_state === "Bullish" && <span className="text-xs">▲</span>}
          {snapshotData.macd_state === "Bearish" && <span className="text-xs">▼</span>}
        </div>
      </div>

      {/* RVOL */}
      <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition-all duration-300 ${getRVOLColor(snapshotData.rvol)} ${isHighVolume ? 'shadow-[0_0_15px_rgba(234,179,8,0.3)]' : ''}`}>
        {isHighVolume ? <Zap className="h-4 w-4" /> : <Activity className="h-4 w-4" />}
        <div className="flex flex-col">
          <span className="text-[10px] font-medium opacity-70">RVOL</span>
          <span className="text-sm font-bold number-mono">{snapshotData.rvol.toFixed(1)}×</span>
          {isHighVolume && <span className="text-xs font-bold">⚡ HIGH</span>}
        </div>
      </div>

      {/* Trend Bias */}
      <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition-all duration-300 ${getTrendColor(snapshotData.trend_bias)}`}>
        <BarChart3 className="h-4 w-4" />
        <div className="flex flex-col">
          <span className="text-[10px] font-medium opacity-70">TREND</span>
          <span className="text-sm font-bold">{snapshotData.trend_bias}</span>
          {snapshotData.trend_bias === "Bullish" && <span className="text-xs">▲</span>}
          {snapshotData.trend_bias === "Bearish" && <span className="text-xs">▼</span>}
        </div>
      </div>

      {/* Volatility Regime */}
      <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition-all duration-300 ${getVolatilityColor(snapshotData.volatility_regime)}`}>
        <Activity className="h-4 w-4" />
        <div className="flex flex-col">
          <span className="text-[10px] font-medium opacity-70">VOLATILITY</span>
          <span className="text-sm font-bold">{snapshotData.volatility_regime}</span>
          {snapshotData.volatility_regime === "High" && <span className="text-xs">⚠️</span>}
        </div>
      </div>
    </div>
  );
};
