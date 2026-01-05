import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Droplets, TrendingUp, Info } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

interface LiquidityKpiProps {
  rvol?: number;
  ticksPerMinute?: number;
  avgTicksPerMinute?: number;
  tradesPerMinute?: number;
  loading?: boolean;
}

export function LiquidityKpi({
  rvol = 2.8,
  ticksPerMinute = 350,
  avgTicksPerMinute = 120,
  tradesPerMinute = 45,
  loading = false,
}: LiquidityKpiProps) {
  const isHighVolume = rvol >= 2.0;
  const volumeRatio = ticksPerMinute / avgTicksPerMinute;

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Droplets className="h-5 w-5" />
            Liquidity & Volume
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 animate-pulse">
            <div className="h-16 bg-muted rounded" />
            <div className="h-10 bg-muted rounded" />
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={isHighVolume ? "border-yellow-200 bg-yellow-50/30" : ""}>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Droplets className="h-5 w-5 text-primary" />
          Liquidity & Volume
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger>
                <Info className="h-4 w-4 text-muted-foreground ml-auto" />
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">
                <p className="text-sm">
                  High relative volume (≥2.0×) indicates strong institutional flow or significant market interest.
                  Increased tick/trade speed suggests active participation.
                </p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Relative Volume */}
        <div className="space-y-2">
          <div className="flex items-baseline justify-between">
            <span className="text-sm text-muted-foreground">Relative Volume</span>
            {isHighVolume && (
              <Badge variant="outline" className="bg-yellow-100 text-yellow-800 border-yellow-300">
                <TrendingUp className="h-3 w-3 mr-1" />
                High
              </Badge>
            )}
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-bold text-primary">
              {rvol.toFixed(1)}×
            </span>
            <span className="text-sm text-muted-foreground">vs 2h avg</span>
          </div>
        </div>

        {/* Volume Speed Metrics */}
        <div className="grid grid-cols-2 gap-4 pt-2 border-t">
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">Ticks/Min</div>
            <div className="text-2xl font-semibold">{ticksPerMinute}</div>
            <div className="text-xs text-muted-foreground">
              vs avg {avgTicksPerMinute}
            </div>
          </div>
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">Trades/Min</div>
            <div className="text-2xl font-semibold">{tradesPerMinute}</div>
            <div className={`text-xs ${volumeRatio >= 2 ? 'text-green-600' : 'text-muted-foreground'}`}>
              {volumeRatio >= 2 ? 'Very Active' : 'Normal'}
            </div>
          </div>
        </div>

        {/* Visual Indicator */}
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">Activity Level</div>
          <div className="flex gap-1">
            {[1, 2, 3, 4, 5].map((level) => (
              <div
                key={level}
                className={`flex-1 h-2 rounded-full ${
                  level <= Math.ceil(rvol)
                    ? isHighVolume
                      ? 'bg-yellow-400'
                      : 'bg-primary'
                    : 'bg-muted'
                }`}
              />
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
