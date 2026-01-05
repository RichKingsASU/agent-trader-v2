import { Card } from "@/components/ui/card";
import { TrendingUp, TrendingDown } from "lucide-react";
import { LineChart, Line, ResponsiveContainer } from "recharts";
import { Skeleton } from "@/components/ui/skeleton";
import { useLiveWatchlist } from "@/hooks/useLiveWatchlist";

interface MarketSymbol {
  symbol: string;
  name: string;
}

const MARKET_SYMBOLS: MarketSymbol[] = [
  { symbol: "SPY", name: "S&P 500" },
  { symbol: "QQQ", name: "Nasdaq" },
  { symbol: "AAPL", name: "Apple" },
  { symbol: "NVDA", name: "NVIDIA" },
];

export function MarketOverview() {
  const { watchlist, loading, status } = useLiveWatchlist();

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
      {MARKET_SYMBOLS.map((market) => {
        const wl = watchlist.find((w) => w.symbol === market.symbol) ?? null;
        const isPositive = (wl?.change ?? 0) >= 0;
        const strokeColor = isPositive ? "hsl(var(--bull))" : "hsl(var(--bear))";
        const series = (wl?.sparklineData ?? []).map((value) => ({ value }));
        
        return (
          <Card key={market.symbol} className="p-4">
            <div className="flex justify-between items-start mb-2">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <h3 className="font-semibold text-sm text-foreground">
                    {market.name}
                  </h3>
                  {!loading && wl ? (
                    isPositive ? (
                      <TrendingUp className="h-3 w-3 text-bull" />
                    ) : (
                      <TrendingDown className="h-3 w-3 text-bear" />
                    )
                  ) : null}
                </div>
                {loading ? (
                  <>
                    <Skeleton className="h-7 w-28 mb-2" />
                    <Skeleton className="h-4 w-36" />
                  </>
                ) : !wl ? (
                  <div className="text-sm text-muted-foreground">
                    {status === "OFFLINE"
                      ? "Offline"
                      : status === "STALE"
                        ? "Stale"
                        : "No quote"}
                  </div>
                ) : (
                  <>
                    <div className="text-xl font-bold text-foreground number-mono">
                      {wl.price.toLocaleString("en-US", {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}
                    </div>
                    <div className={`text-sm font-medium ${isPositive ? "text-bull" : "text-bear"} number-mono`}>
                      {isPositive ? "+" : ""}
                      {wl.change.toFixed(2)} ({isPositive ? "+" : ""}
                      {wl.changePct.toFixed(2)}%)
                    </div>
                  </>
                )}
              </div>
              <div className="w-24 h-16">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={series}>
                    <Line
                      type="monotone"
                      dataKey="value"
                      stroke={strokeColor}
                      strokeWidth={1.5}
                      dot={false}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
