import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown, DollarSign, Target, Eye } from "lucide-react";
import { useShadowTrades } from "@/hooks/useShadowTrades";
import { formatUsd2 } from "@/lib/utils";

/**
 * ShadowPortfolio - Shadow Trade P&L Tracking Component
 * 
 * Displays real-time synthetic portfolio value and P&L from shadow trades.
 * Shows "What-If" wealth based on simulated trades.
 * 
 * Features:
 * - Real-time P&L updates via Firestore listeners
 * - Total synthetic equity calculation
 * - Individual position tracking
 * - Visual P&L indicators
 */
export const ShadowPortfolio = () => {
  const { trades, summary, loading, error } = useShadowTrades();

  const formatPercent = (percent: number): string => {
    const sign = percent >= 0 ? "+" : "";
    return `${sign}${percent.toFixed(2)}%`;
  };

  const getPnLColor = (pnl: number) => {
    if (pnl > 0) return "bull-text";
    if (pnl < 0) return "bear-text";
    return "text-muted-foreground";
  };

  const getPnLBgGradient = (pnl: number) => {
    if (pnl > 0) return "from-green-500/5 to-green-500/10 border-green-500/20";
    if (pnl < 0) return "from-red-500/5 to-red-500/10 border-red-500/20";
    return "from-muted/5 to-muted/10 border-muted/20";
  };

  return (
    <Card className={`p-4 border-2 bg-gradient-to-br ${getPnLBgGradient(summary.totalPnL)}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Eye className="h-4 w-4 text-primary" />
          <h3 className="text-xs font-bold text-primary uppercase tracking-wider ui-label">
            Shadow Portfolio
          </h3>
        </div>
        <Badge variant="outline" className="text-[10px] px-2 py-0.5">
          {summary.openPositions} Open {summary.openPositions === 1 ? "Position" : "Positions"}
        </Badge>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-md p-3 mb-3">
          <p className="text-xs text-destructive font-medium">{error}</p>
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div className="animate-pulse space-y-3">
          <div className="h-20 bg-muted rounded"></div>
          <div className="h-16 bg-muted rounded"></div>
        </div>
      )}

      {/* Portfolio Summary */}
      {!loading && !error && (
        <div className="space-y-4">
          {/* Total Synthetic Equity */}
          <div className="bg-background/60 border border-white/10 rounded-lg p-4">
            <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-2 font-medium ui-label">
              Total Synthetic Value
            </div>
            <div className="flex items-baseline gap-2 mb-3">
              <DollarSign className="h-5 w-5 text-foreground mt-1" />
              <div className="number-mono text-3xl font-bold text-foreground">
                {formatUsd2(summary.totalValue)}
              </div>
            </div>

            {/* P&L Display */}
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-background/80 border border-white/10 rounded-md p-3">
                <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">
                  Total P&L
                </div>
                <div className={`flex items-center gap-1 ${getPnLColor(summary.totalPnL)}`}>
                  {summary.totalPnL > 0 ? (
                    <TrendingUp className="h-4 w-4" />
                  ) : summary.totalPnL < 0 ? (
                    <TrendingDown className="h-4 w-4" />
                  ) : null}
                  <div className="number-mono text-xl font-bold">
                    {formatUsd2(summary.totalPnL)}
                  </div>
                </div>
              </div>

              <div className="bg-background/80 border border-white/10 rounded-md p-3">
                <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">
                  P&L %
                </div>
                <div className={`flex items-center gap-1 ${getPnLColor(summary.totalPnL)}`}>
                  <Target className="h-4 w-4" />
                  <div className="number-mono text-xl font-bold">
                    {formatPercent(summary.totalPnLPercent)}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Open Positions List */}
          {trades.length > 0 && (
            <div className="space-y-2">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium ui-label">
                Open Positions
              </div>
              <div className="space-y-2 max-h-60 overflow-y-auto">
                {trades.map((trade) => {
                  const pnl = parseFloat(trade.current_pnl || "0");
                  const pnlPercent = parseFloat(trade.pnl_percent || "0");
                  const entryPrice = parseFloat(trade.entry_price || "0");
                  const currentPrice = parseFloat(trade.current_price || "0");
                  const quantity = parseFloat(trade.quantity || "0");

                  return (
                    <div
                      key={trade.id}
                      className="bg-background/60 border border-white/10 rounded-md p-3 hover:bg-background/80 transition-colors"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <Badge
                            variant="outline"
                            className={`text-[10px] px-2 py-0 ${
                              trade.side === "BUY" ? "border-green-500/50 text-green-500" : "border-red-500/50 text-red-500"
                            }`}
                          >
                            {trade.side}
                          </Badge>
                          <span className="font-bold text-sm text-foreground">{trade.symbol}</span>
                          <span className="text-xs text-muted-foreground">×{quantity}</span>
                        </div>
                        <div className={`text-right ${getPnLColor(pnl)}`}>
                          <div className="text-xs font-bold">{formatUsd2(pnl)}</div>
                          <div className="text-[10px]">{formatPercent(pnlPercent)}</div>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-2 text-[10px]">
                        <div>
                          <span className="text-muted-foreground">Entry: </span>
                          <span className="number-mono font-semibold text-foreground">
                            ${entryPrice.toFixed(2)}
                          </span>
                        </div>
                        <div>
                          <span className="text-muted-foreground">Current: </span>
                          <span className="number-mono font-semibold text-foreground">
                            ${currentPrice.toFixed(2)}
                          </span>
                        </div>
                      </div>

                      {trade.reasoning && (
                        <div className="mt-2 text-[10px] text-muted-foreground italic truncate">
                          {trade.reasoning}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Empty State */}
          {trades.length === 0 && !loading && (
            <div className="text-center py-8 bg-background/60 border border-white/10 rounded-lg">
              <Eye className="h-10 w-10 text-muted-foreground/30 mx-auto mb-2" />
              <p className="text-sm text-muted-foreground mb-1">No shadow trades yet</p>
              <p className="text-xs text-muted-foreground/70">
                Execute shadow trades to see your synthetic portfolio
              </p>
            </div>
          )}
        </div>
      )}
    </Card>
  );
};
