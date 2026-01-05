import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { TrendingUp, TrendingDown, Wallet, Zap, Settings } from "lucide-react";
import { formatUsd0, formatUsd2 } from "@/lib/formatters";

interface VitalsBarProps {
  equity: number;
  buyingPower: number;
  maxBuyingPower: number;
  cash?: number;
  dayPnl: number;
  dayPnlPct: number;
  loading?: boolean;
  hasCache?: boolean;
}

export const VitalsBar = ({
  equity,
  buyingPower,
  maxBuyingPower,
  cash = 0,
  dayPnl,
  dayPnlPct,
  loading = false,
  hasCache = true,
}: VitalsBarProps) => {
  const safeMax = Number.isFinite(maxBuyingPower) && maxBuyingPower > 0 ? maxBuyingPower : Math.max(buyingPower, 1);
  const buyingPowerPct = (buyingPower / safeMax) * 100;
  const isProfitable = dayPnl >= 0;
  const showPlaceholder = loading && !hasCache;

  return (
    <Card className="bg-card/50 backdrop-blur-md border-white/10 border-t-2">
      <div className="px-6 py-3 flex items-center justify-between gap-8">
        {/* Account Equity */}
        <div className="flex items-center gap-3">
          <div className="w-1 h-10 bg-primary rounded-full" />
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground ui-label flex items-center gap-1.5">
              <Wallet className="h-3 w-3" />
              Account Equity
            </div>
            <div className="text-xl font-extrabold number-mono">
              {formatUsd2(equity)}
            </div>
          </div>
        </div>

        {/* Buying Power Gauge */}
        <div className="flex-1 max-w-md">
          <div className="flex items-center justify-between mb-1.5">
            <div className="text-xs uppercase tracking-wider text-muted-foreground ui-label flex items-center gap-1.5">
              <Zap className="h-3 w-3" />
              Buying Power
            </div>
            <div className="text-sm font-bold number-mono">
              {formatUsd0(buyingPower)}
            </div>
          </div>
          <Progress
            value={showPlaceholder ? 0 : buyingPowerPct}
            className="h-2 bg-background/50"
            indicatorClassName={
              buyingPowerPct > 75
                ? "bg-bull"
                : buyingPowerPct > 40
                ? "bg-yellow-500"
                : "bg-bear"
            }
          />
          <div className="text-xs text-muted-foreground mt-1 number-mono">
            {showPlaceholder ? "--" : `${buyingPowerPct.toFixed(0)}% Available`}
          </div>
        </div>

        {/* Cash */}
        <div className="flex items-center gap-3">
          <div className="w-1 h-10 bg-accent rounded-full" />
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground ui-label flex items-center gap-1.5">
              <Wallet className="h-3 w-3" />
              Cash
            </div>
            <div className="text-xl font-extrabold number-mono">
              {showPlaceholder ? "--" : formatUsd2(cash)}
            </div>
          </div>
        </div>

        {/* Total Day P&L */}
        <div className="flex items-center gap-3">
          <div className={`w-1 h-10 rounded-full ${isProfitable ? "bg-bull" : "bg-bear"}`} />
          <div>
            <div className="text-xs uppercase tracking-wider text-muted-foreground ui-label flex items-center gap-1.5">
              {isProfitable ? (
                <TrendingUp className="h-3 w-3 text-bull" />
              ) : (
                <TrendingDown className="h-3 w-3 text-bear" />
              )}
              Total Day P&L
            </div>
            <div className={`text-xl font-extrabold number-mono ${isProfitable ? "text-bull" : "text-bear"}`}>
              {dayPnl >= 0 ? "+" : "-"}
              {formatUsd2(Math.abs(dayPnl))}
              <span className="ml-2 text-base font-bold">
                ({dayPnlPct >= 0 ? "+" : ""}{dayPnlPct.toFixed(2)}%)
              </span>
            </div>
          </div>
        </div>

        {/* Developer Link */}
        <Button variant="ghost" size="sm" asChild className="text-muted-foreground hover:text-foreground">
          <Link to="/developer">
            <Settings className="h-4 w-4 mr-1.5" />
            Dev
          </Link>
        </Button>
      </div>
    </Card>
  );
};
