import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Activity, TrendingUp, BarChart3, Gauge } from "lucide-react";

interface FlowMomentumProps {
  snapshotData: any;
  loading: boolean;
}

export const FlowMomentum = ({ snapshotData, loading }: FlowMomentumProps) => {
  if (loading || !snapshotData) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-32" />
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </CardContent>
      </Card>
    );
  }

  const getRSIVariant = (zone: string) => {
    if (zone === "Overbought") return "destructive";
    if (zone === "Bullish") return "default";
    if (zone === "Bearish") return "secondary";
    return "outline";
  };

  const getMACDVariant = (state: string) => {
    if (state === "Bullish") return "default";
    if (state === "Bearish") return "destructive";
    return "outline";
  };

  const getVolatilityColor = (regime: string) => {
    if (regime === "High") return "text-warning";
    if (regime === "Low") return "text-neutral";
    return "text-foreground";
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Flow & Momentum</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* RVOL */}
        <div className={`text-center p-3 rounded-lg ${snapshotData.rvol >= 2.0 ? 'bg-yellow-50' : ''}`}>
          <div className="flex items-center justify-center gap-2 mb-2">
            <Activity className="h-4 w-4 text-primary" />
            <span className="text-xs font-medium text-muted-foreground">
              {snapshotData.rvol >= 2.0 ? `${snapshotData.rvol.toFixed(1)}× Volume` : 'Relative Volume'}
            </span>
          </div>
          <div className="flex items-center justify-center">
            <div className="relative w-20 h-20">
              <svg className="transform -rotate-90 w-20 h-20">
                <circle
                  cx="40"
                  cy="40"
                  r="32"
                  stroke="hsl(var(--muted))"
                  strokeWidth="8"
                  fill="none"
                />
                <circle
                  cx="40"
                  cy="40"
                  r="32"
                  stroke="hsl(var(--primary))"
                  strokeWidth="8"
                  fill="none"
                  strokeDasharray={`${Math.min(snapshotData.rvol / 5, 1) * 201} 201`}
                  strokeLinecap="round"
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-2xl font-bold number-mono">{snapshotData.rvol.toFixed(1)}</span>
                <span className="text-xs text-muted-foreground">× Avg</span>
              </div>
            </div>
          </div>
        </div>

        {/* Indicators */}
        <div className="space-y-2">
          {/* RSI */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Gauge className="h-3 w-3 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">RSI Zone</span>
            </div>
            <Badge variant={getRSIVariant(snapshotData.rsi_zone)} className="text-xs">
              {snapshotData.rsi_zone} ({snapshotData.rsi_14})
            </Badge>
          </div>

          {/* MACD */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-3 w-3 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">MACD State</span>
            </div>
            <Badge variant={getMACDVariant(snapshotData.macd_state)} className="text-xs">
              {snapshotData.macd_state}
            </Badge>
          </div>

          {/* Bollinger State */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <BarChart3 className="h-3 w-3 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">Bollinger</span>
            </div>
            <Badge variant="outline" className="text-xs">
              {snapshotData.bb_state}
            </Badge>
          </div>

          {/* Volatility Regime */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className="h-3 w-3 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">Volatility</span>
            </div>
            <Badge variant="outline" className={`text-xs ${getVolatilityColor(snapshotData.volatility_regime)}`}>
              {snapshotData.volatility_regime}
            </Badge>
          </div>
        </div>

        {/* Summary */}
        <div className="pt-3 border-t border-border">
          <p className="text-xs text-muted-foreground italic">
            {snapshotData.rvol > 2 && snapshotData.rsi_zone === "Bullish" 
              ? "Strong momentum with elevated volume - move likely to continue."
              : snapshotData.rvol < 1 && snapshotData.rsi_zone === "Overbought"
              ? "Weak volume on overbought condition - potential exhaustion."
              : snapshotData.volatility_regime === "High"
              ? "High volatility regime - expect larger price swings."
              : "Normal market conditions - standard risk parameters apply."}
          </p>
        </div>
      </CardContent>
    </Card>
  );
};
