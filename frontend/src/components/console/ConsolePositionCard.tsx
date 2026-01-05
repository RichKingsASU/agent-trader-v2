import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TrendingUp, TrendingDown } from "lucide-react";

interface ConsolePositionCardProps {
  symbol: string;
  currentPrice?: number;
  levelsData: any;
  loading: boolean;
}

export const ConsolePositionCard = ({ symbol, currentPrice, levelsData, loading }: ConsolePositionCardProps) => {
  const [positions, setPositions] = useState<any[]>([]);

  useEffect(() => {
    // Mock options positions - replace with actual API call
    setPositions([
      {
        underlying: "SPY",
        contract: "19Dec25 430C",
        quantity: 5,
        entry_price: 3.20,
        current_price: 3.85,
        pnl: 325.00,
        delta: 28.5,
        theta: -12.3,
        vega: 18.7,
      },
    ]);
  }, [symbol]);

  const symbolPositions = positions.filter(p => p.underlying === symbol);
  const hasPosition = symbolPositions.length > 0;

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-32" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!hasPosition) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Your Position on {symbol}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-6">
            <p className="text-sm text-muted-foreground">No open options position on this symbol.</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const position = symbolPositions[0];

  // Calculate what-if scenarios
  const calculateWhatIf = () => {
    if (!currentPrice || !levelsData) return { toFloor: 0, toCeiling: 0 };

    const floors = [
      levelsData.orl_5m,
      levelsData.premarket_low,
      levelsData.intraday_low,
      levelsData.prev_day_low,
    ].filter(l => l < currentPrice);

    const ceilings = [
      levelsData.orh_5m,
      levelsData.premarket_high,
      levelsData.intraday_high,
      levelsData.prev_day_high,
    ].filter(l => l > currentPrice);

    const nearestFloor = floors.length > 0 ? Math.max(...floors) : currentPrice * 0.99;
    const nearestCeiling = ceilings.length > 0 ? Math.min(...ceilings) : currentPrice * 1.01;

    const priceChangeToFloor = nearestFloor - currentPrice;
    const priceChangeToCeiling = nearestCeiling - currentPrice;

    // Simple delta approximation: P&L = delta * price_change * 100 * quantity
    const pnlToFloor = (position.delta * priceChangeToFloor * 100 * position.quantity) / 100;
    const pnlToCeiling = (position.delta * priceChangeToCeiling * 100 * position.quantity) / 100;

    return { toFloor: pnlToFloor, toCeiling: pnlToCeiling };
  };

  const whatIf = calculateWhatIf();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Your Position on {symbol}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Position Summary */}
        <div className="p-3 bg-muted/50 rounded-lg space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium">{position.contract}</span>
            <Badge variant={position.pnl >= 0 ? "default" : "destructive"}>
              {position.quantity > 0 ? "+" : ""}{position.quantity}
            </Badge>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">P&L</span>
            <span className={`text-sm font-semibold number-mono ${position.pnl >= 0 ? "text-bull" : "text-bear"}`}>
              {position.pnl >= 0 ? "+" : ""}${position.pnl.toFixed(2)}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2 pt-2 border-t border-border">
            <div className="text-center">
              <div className="text-xs text-muted-foreground">Delta</div>
              <div className="text-xs font-medium number-mono">{position.delta.toFixed(1)}</div>
            </div>
            <div className="text-center">
              <div className="text-xs text-muted-foreground">Theta</div>
              <div className="text-xs font-medium number-mono">{position.theta.toFixed(1)}</div>
            </div>
            <div className="text-center">
              <div className="text-xs text-muted-foreground">Vega</div>
              <div className="text-xs font-medium number-mono">{position.vega.toFixed(1)}</div>
            </div>
          </div>
        </div>

        {/* What-If Scenarios */}
        <div className="space-y-2">
          <h4 className="text-xs font-semibold text-muted-foreground">What-If Analysis</h4>
          
          <div className="flex items-center justify-between p-2 border border-border rounded">
            <div className="flex items-center gap-2">
              <TrendingDown className="h-3 w-3 text-bear" />
              <span className="text-xs">If price to next floor:</span>
            </div>
            <span className={`text-sm font-semibold number-mono ${whatIf.toFloor >= 0 ? "text-bull" : "text-bear"}`}>
              {whatIf.toFloor >= 0 ? "+" : ""}${whatIf.toFloor.toFixed(2)}
            </span>
          </div>

          <div className="flex items-center justify-between p-2 border border-border rounded">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-3 w-3 text-bull" />
              <span className="text-xs">If price to next ceiling:</span>
            </div>
            <span className={`text-sm font-semibold number-mono ${whatIf.toCeiling >= 0 ? "text-bull" : "text-bear"}`}>
              {whatIf.toCeiling >= 0 ? "+" : ""}${whatIf.toCeiling.toFixed(2)}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
