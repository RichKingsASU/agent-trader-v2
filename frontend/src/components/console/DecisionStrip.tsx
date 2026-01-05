import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TrendingUp, TrendingDown } from "lucide-react";

interface DecisionStripProps {
  snapshotData: any;
  levelsData: any;
  loading: boolean;
}

export const DecisionStrip = ({ snapshotData, levelsData, loading }: DecisionStripProps) => {
  if (loading || !snapshotData || !levelsData) {
    return (
      <Card>
        <CardContent className="p-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        </CardContent>
      </Card>
    );
  }

  const currentPrice = snapshotData.last_price;
  const atr = snapshotData.atr_14;

  // Find nearest ceiling and floor
  const levels = [
    { name: "Daily High", price: levelsData.daily_high },
    { name: "PDH", price: levelsData.prev_day_high },
    { name: "4H High", price: levelsData.hour_4_high },
    { name: "Intraday High", price: levelsData.intraday_high },
    { name: "PMH", price: levelsData.premarket_high },
    { name: "ORH", price: levelsData.orh_5m },
    { name: "ORL", price: levelsData.orl_5m },
    { name: "PML", price: levelsData.premarket_low },
    { name: "Intraday Low", price: levelsData.intraday_low },
    { name: "4H Low", price: levelsData.hour_4_low },
    { name: "PDL", price: levelsData.prev_day_low },
    { name: "Daily Low", price: levelsData.daily_low },
  ];

  const ceilings = levels.filter(l => l.price > currentPrice).sort((a, b) => a.price - b.price);
  const floors = levels.filter(l => l.price < currentPrice).sort((a, b) => b.price - a.price);

  const nearestCeiling = ceilings[0];
  const nearestFloor = floors[0];

  // Calculate R:R for hold scenario
  const holdRisk = nearestFloor ? currentPrice - nearestFloor.price : 0;
  const holdReward = nearestCeiling ? nearestCeiling.price - currentPrice : 0;
  const holdRiskPct = (holdRisk / currentPrice) * 100;
  const holdRewardPct = (holdReward / currentPrice) * 100;
  const holdRiskATR = holdRisk / atr;
  const holdRewardATR = holdReward / atr;
  const holdRR = holdRisk > 0 ? holdReward / holdRisk : 0;

  // Calculate R:R for new long scenario
  const longStop = nearestFloor?.price || currentPrice - atr;
  const longTarget = nearestCeiling?.price || currentPrice + atr * 2;
  const longRisk = currentPrice - longStop;
  const longReward = longTarget - currentPrice;
  const longRiskPct = (longRisk / currentPrice) * 100;
  const longRewardPct = (longReward / currentPrice) * 100;
  const longRiskATR = longRisk / atr;
  const longRewardATR = longReward / atr;
  const longRR = longRisk > 0 ? longReward / longRisk : 0;

  // Calculate R:R for new short scenario
  const shortStop = nearestCeiling?.price || currentPrice + atr;
  const shortTarget = nearestFloor?.price || currentPrice - atr * 2;
  const shortRisk = shortStop - currentPrice;
  const shortReward = currentPrice - shortTarget;
  const shortRiskPct = (shortRisk / currentPrice) * 100;
  const shortRewardPct = (shortReward / currentPrice) * 100;
  const shortRiskATR = shortRisk / atr;
  const shortRewardATR = shortReward / atr;
  const shortRR = shortRisk > 0 ? shortReward / shortRisk : 0;

  const getRRColor = (rr: number) => {
    if (rr >= 2) return "text-bull";
    if (rr >= 1) return "text-neutral";
    return "text-bear";
  };

  const getRRBadgeVariant = (rr: number): "default" | "secondary" | "destructive" => {
    if (rr >= 2) return "default";
    if (rr >= 1) return "secondary";
    return "destructive";
  };

  return (
    <Card>
      <CardContent className="p-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Hold Scenario */}
          <div className="border border-border rounded-lg p-4 space-y-2">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-primary" />
              Hold Scenario
            </h3>
            <div className="space-y-1 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Risk to {nearestFloor?.name || "Floor"}:</span>
                <span className="text-bear number-mono">
                  -{holdRiskPct.toFixed(2)}% / -{holdRiskATR.toFixed(2)}× ATR
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Reward to {nearestCeiling?.name || "Ceiling"}:</span>
                <span className="text-bull number-mono">
                  +{holdRewardPct.toFixed(2)}% / +{holdRewardATR.toFixed(2)}× ATR
                </span>
              </div>
              <div className="flex justify-between items-center pt-2 border-t border-border mt-2">
                <span className="font-medium">R:R Hold:</span>
                <Badge variant={getRRBadgeVariant(holdRR)} className={getRRColor(holdRR)}>
                  1:{holdRR.toFixed(2)}
                </Badge>
              </div>
            </div>
          </div>

          {/* New Position Scenarios */}
          <div className="border border-border rounded-lg p-4 space-y-3">
            <h3 className="text-sm font-semibold">New Position Scenarios</h3>
            
            {/* Long */}
            <div className="space-y-1 text-xs">
              <div className="flex items-center gap-2 mb-1">
                <TrendingUp className="h-3 w-3 text-bull" />
                <span className="font-medium text-bull">Long Entry</span>
              </div>
              <div className="flex justify-between text-muted-foreground">
                <span>Stop: {nearestFloor?.name || "Floor"}</span>
                <span className="number-mono">${longStop.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-muted-foreground">
                <span>Target: {nearestCeiling?.name || "Ceiling"}</span>
                <span className="number-mono">${longTarget.toFixed(2)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span>R:R:</span>
                <Badge variant={getRRBadgeVariant(longRR)} className={`${getRRColor(longRR)} text-xs`}>
                  1:{longRR.toFixed(2)}
                </Badge>
              </div>
            </div>

            <div className="border-t border-border" />

            {/* Short */}
            <div className="space-y-1 text-xs">
              <div className="flex items-center gap-2 mb-1">
                <TrendingDown className="h-3 w-3 text-bear" />
                <span className="font-medium text-bear">Short Entry</span>
              </div>
              <div className="flex justify-between text-muted-foreground">
                <span>Stop: {nearestCeiling?.name || "Ceiling"}</span>
                <span className="number-mono">${shortStop.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-muted-foreground">
                <span>Target: {nearestFloor?.name || "Floor"}</span>
                <span className="number-mono">${shortTarget.toFixed(2)}</span>
              </div>
              <div className="flex justify-between items-center">
                <span>R:R:</span>
                <Badge variant={getRRBadgeVariant(shortRR)} className={`${getRRColor(shortRR)} text-xs`}>
                  1:{shortRR.toFixed(2)}
                </Badge>
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
