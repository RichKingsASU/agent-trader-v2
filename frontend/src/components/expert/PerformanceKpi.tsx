import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, Info, Target } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

interface PerformanceKpiProps {
  winRate?: number;
  avgRR?: number;
  edge?: number;
  totalTrades?: number;
  loading?: boolean;
}

export function PerformanceKpi({
  winRate = 72,
  avgRR = 2.3,
  edge = 0.34,
  totalTrades = 50,
  loading = false,
}: PerformanceKpiProps) {
  const isGoodWinRate = winRate >= 50;
  const isGoodRR = avgRR >= 1.5;
  const isPositiveEdge = edge > 0;

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Target className="h-5 w-5" />
            Recent Performance
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 animate-pulse">
            <div className="h-16 bg-muted rounded" />
            <div className="h-16 bg-muted rounded" />
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={isPositiveEdge ? "border-green-200 bg-green-50/30" : ""}>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          <Target className="h-5 w-5 text-primary" />
          Recent Performance
          <Badge variant="outline" className="ml-auto text-xs">
            Last {totalTrades} trades
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Win Rate */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Win Rate</span>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger>
                  <Info className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-sm max-w-xs">
                    Percentage of trades that closed with profit. A win rate above 50% indicates consistency.
                  </p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
          <div className="flex items-baseline gap-2">
            <span className={`text-3xl font-bold ${isGoodWinRate ? 'text-green-600' : 'text-red-600'}`}>
              {winRate.toFixed(0)}%
            </span>
            {isGoodWinRate && (
              <TrendingUp className="h-5 w-5 text-green-600" />
            )}
          </div>
          {/* Win Rate Visual */}
          <div className="relative w-full h-2 bg-muted rounded-full overflow-hidden">
            <div
              className={`absolute left-0 top-0 h-full ${isGoodWinRate ? 'bg-green-600' : 'bg-red-600'} transition-all`}
              style={{ width: `${Math.min(winRate, 100)}%` }}
            />
          </div>
        </div>

        {/* Average R:R */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Avg Risk:Reward</span>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger>
                  <Info className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-sm max-w-xs">
                    Average reward-to-risk ratio achieved across trades. Values above 1.5:1 are considered strong.
                  </p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-2xl font-bold">1 :</span>
            <span className={`text-3xl font-bold ${isGoodRR ? 'text-green-600' : 'text-muted-foreground'}`}>
              {avgRR.toFixed(1)}
            </span>
          </div>
        </div>

        {/* Trading Edge */}
        <div className="pt-2 border-t space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Trading Edge</span>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger>
                  <Info className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-sm max-w-xs">
                    Edge = (Avg Win × Win Rate) - (Avg Loss × Loss Rate). Positive edge means profitable system over time.
                  </p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm">Edge =</span>
            <span className={`text-2xl font-bold ${isPositiveEdge ? 'text-green-600' : 'text-red-600'}`}>
              {isPositiveEdge ? '+' : ''}{edge.toFixed(2)}
            </span>
          </div>
          {isPositiveEdge ? (
            <p className="text-xs text-green-700 bg-green-100 px-2 py-1 rounded">
              ✓ Positive edge — system is profitable long-term
            </p>
          ) : (
            <p className="text-xs text-red-700 bg-red-100 px-2 py-1 rounded">
              ⚠ Negative edge — review strategy
            </p>
          )}
        </div>

        {/* Stats Summary */}
        <div className="grid grid-cols-2 gap-2 pt-2 border-t text-xs">
          <div className="space-y-1">
            <div className="text-muted-foreground">Total Trades</div>
            <div className="font-semibold">{totalTrades}</div>
          </div>
          <div className="space-y-1">
            <div className="text-muted-foreground">Wins</div>
            <div className="font-semibold text-green-600">
              {Math.round((winRate / 100) * totalTrades)}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
