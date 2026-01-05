import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface StructureMapProps {
  snapshotData: any;
  levelsData: any;
  loading: boolean;
}

export const StructureMap = ({ snapshotData, levelsData, loading }: StructureMapProps) => {
  if (loading || !snapshotData || !levelsData) {
    return (
      <div className="space-y-4">
        <Card>
          <CardHeader>
            <Skeleton className="h-5 w-40" />
          </CardHeader>
          <CardContent className="space-y-3">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </CardContent>
        </Card>
      </div>
    );
  }

  const currentPrice = snapshotData.last_price;
  const atr = snapshotData.atr_14;

  // Calculate timeframe positions
  const dailyMid = (levelsData.daily_high + levelsData.daily_low) / 2;
  const dailyRange = levelsData.daily_high - levelsData.daily_low;
  const dailyPosition = ((currentPrice - levelsData.daily_low) / dailyRange) * 100;

  const hour4Mid = (levelsData.hour_4_high + levelsData.hour_4_low) / 2;
  const hour4Range = levelsData.hour_4_high - levelsData.hour_4_low;
  const hour4Position = ((currentPrice - levelsData.hour_4_low) / hour4Range) * 100;

  const hour1Mid = (levelsData.hour_1_high + levelsData.hour_1_low) / 2;
  const hour1Range = levelsData.hour_1_high - levelsData.hour_1_low;
  const hour1Position = ((currentPrice - levelsData.hour_1_low) / hour1Range) * 100;

  // Build support/resistance ladder
  const levels = [
    { name: "Daily High", price: levelsData.daily_high, type: "resistance" },
    { name: "PDH", price: levelsData.prev_day_high, type: "resistance" },
    { name: "4H High", price: levelsData.hour_4_high, type: "resistance" },
    { name: "Intraday High", price: levelsData.intraday_high, type: "resistance" },
    { name: "PMH", price: levelsData.premarket_high, type: "resistance" },
    { name: "ORH", price: levelsData.orh_5m, type: "resistance" },
    { name: "VWAP", price: snapshotData.vwap, type: "pivot" },
    { name: "ORL", price: levelsData.orl_5m, type: "support" },
    { name: "PML", price: levelsData.premarket_low, type: "support" },
    { name: "Intraday Low", price: levelsData.intraday_low, type: "support" },
    { name: "4H Low", price: levelsData.hour_4_low, type: "support" },
    { name: "PDL", price: levelsData.prev_day_low, type: "support" },
    { name: "Daily Low", price: levelsData.daily_low, type: "support" },
  ];

  const ceilings = levels.filter(l => l.price > currentPrice).sort((a, b) => a.price - b.price);
  const floors = levels.filter(l => l.price < currentPrice).sort((a, b) => b.price - a.price);
  const nearestCeiling = ceilings[0];
  const nearestFloor = floors[0];

  const calculateDistance = (level: number) => {
    const pctDist = ((level - currentPrice) / currentPrice) * 100;
    const atrDist = Math.abs(level - currentPrice) / atr;
    return { pctDist, atrDist };
  };

  // ATR zone calculations (±0.25 ATR around each level)
  const atrZoneWidth = 0.25 * atr;
  const isInDangerZone = (levelPrice: number) => {
    const distance = Math.abs(currentPrice - levelPrice);
    return distance <= atrZoneWidth;
  };

  // Structure summary
  const vwapDist = calculateDistance(snapshotData.vwap);
  const pdhDist = calculateDistance(levelsData.prev_day_high);

  return (
    <div className="space-y-4">
      {/* Multi-Timeframe Structure */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Multi-Timeframe Structure</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* Daily */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-muted-foreground">Daily</span>
              <Badge variant="outline" className="text-xs">
                {dailyPosition > 66 ? "Near High" : dailyPosition < 33 ? "Near Low" : "Mid-Range"}
              </Badge>
            </div>
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <div 
                className="h-full bg-primary transition-all"
                style={{ width: `${dailyPosition}%` }}
              />
            </div>
          </div>

          {/* 4H */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-muted-foreground">4-Hour</span>
              <Badge variant="outline" className="text-xs">
                {hour4Position > 66 ? "Near High" : hour4Position < 33 ? "Near Low" : "Mid-Range"}
              </Badge>
            </div>
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <div 
                className="h-full bg-primary transition-all"
                style={{ width: `${hour4Position}%` }}
              />
            </div>
          </div>

          {/* 1H */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-muted-foreground">1-Hour</span>
              <Badge variant="outline" className="text-xs">
                {hour1Position > 66 ? "Near High" : hour1Position < 33 ? "Near Low" : "Mid-Range"}
              </Badge>
            </div>
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <div 
                className="h-full bg-primary transition-all"
                style={{ width: `${hour1Position}%` }}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Support/Resistance Ladder */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Support / Resistance Ladder</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Ceilings */}
          <div>
            <h4 className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1">
              <TrendingUp className="h-3 w-3" />
              Ceilings (Above)
            </h4>
            <div className="space-y-2">
              {ceilings.slice(0, 4).map((level, idx) => {
                const dist = calculateDistance(level.price);
                const isNearest = idx === 0;
                const inDangerZone = isInDangerZone(level.price);
                return (
                  <div 
                    key={level.name} 
                    className={`p-2 rounded border ${
                      inDangerZone 
                        ? "border-yellow-300 bg-yellow-50" 
                        : isNearest 
                          ? "border-bull bg-bull-muted" 
                          : "border-border"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium">{level.name}</span>
                        {isNearest && <Badge variant="outline" className="text-xs">Nearest</Badge>}
                        {inDangerZone && (
                          <Badge variant="outline" className="text-xs bg-yellow-100 text-yellow-800 border-yellow-300">
                            ATR Zone
                          </Badge>
                        )}
                      </div>
                      <span className="text-sm font-semibold number-mono">${level.price.toFixed(2)}</span>
                    </div>
                    <div className="flex gap-3 mt-1 text-xs text-muted-foreground">
                      <span>+{dist.pctDist.toFixed(2)}%</span>
                      <span>{dist.atrDist.toFixed(2)}× ATR</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Current Price */}
          <div className="p-2 bg-primary/10 border-2 border-primary rounded">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-primary flex items-center gap-1">
                <Minus className="h-3 w-3" />
                CURRENT
              </span>
              <span className="text-sm font-bold number-mono">${currentPrice.toFixed(2)}</span>
            </div>
          </div>

          {/* Floors */}
          <div>
            <h4 className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1">
              <TrendingDown className="h-3 w-3" />
              Floors (Below)
            </h4>
            <div className="space-y-2">
              {floors.slice(0, 4).map((level, idx) => {
                const dist = calculateDistance(level.price);
                const isNearest = idx === 0;
                const inDangerZone = isInDangerZone(level.price);
                return (
                  <div 
                    key={level.name} 
                    className={`p-2 rounded border ${
                      inDangerZone 
                        ? "border-yellow-300 bg-yellow-50" 
                        : isNearest 
                          ? "border-bear bg-bear-muted" 
                          : "border-border"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium">{level.name}</span>
                        {isNearest && <Badge variant="outline" className="text-xs">Nearest</Badge>}
                        {inDangerZone && (
                          <Badge variant="outline" className="text-xs bg-yellow-100 text-yellow-800 border-yellow-300">
                            ATR Zone
                          </Badge>
                        )}
                      </div>
                      <span className="text-sm font-semibold number-mono">${level.price.toFixed(2)}</span>
                    </div>
                    <div className="flex gap-3 mt-1 text-xs text-muted-foreground">
                      <span>{dist.pctDist.toFixed(2)}%</span>
                      <span>{dist.atrDist.toFixed(2)}× ATR</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Structure Summary */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Structure Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2 text-sm text-foreground">
            <p>
              Currently trading <span className="font-semibold">{Math.abs(pdhDist.pctDist).toFixed(2)}%</span>{" "}
              {pdhDist.pctDist > 0 ? "above" : "below"} Prev Day High and{" "}
              <span className="font-semibold">{Math.abs(vwapDist.pctDist).toFixed(2)}%</span>{" "}
              {vwapDist.pctDist > 0 ? "above" : "below"} VWAP.
            </p>
            {currentPrice > levelsData.orl_5m && currentPrice < levelsData.orh_5m ? (
              <p className="text-neutral">Inside opening range; no clear break yet.</p>
            ) : currentPrice >= levelsData.orh_5m ? (
              <p className="text-bull">Trading above opening range high.</p>
            ) : (
              <p className="text-bear">Trading below opening range low.</p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
