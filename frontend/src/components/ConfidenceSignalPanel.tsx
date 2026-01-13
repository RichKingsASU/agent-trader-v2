import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatUsd2 } from "@/lib/utils";
import { Shield, TrendingDown, TrendingUp, Timer } from "lucide-react";
import { usePaperTradingConfidence } from "@/hooks/usePaperTradingConfidence";

function pnlClass(v: number) {
  if (v > 0) return "bull-text";
  if (v < 0) return "bear-text";
  return "text-muted-foreground";
}

export function ConfidenceSignalPanel() {
  const snap = usePaperTradingConfidence();

  return (
    <Card className="p-4 border-2 border-primary/20 bg-gradient-to-br from-primary/5 to-primary/10">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-primary" />
          <h3 className="text-xs font-bold text-primary uppercase tracking-wider ui-label">Confidence Signal</h3>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-[10px]">
            {snap.open_positions_count} Open
          </Badge>
          <Badge
            variant="outline"
            className={`text-[10px] ${
              snap.freshness === "LIVE"
                ? "border-green-500/40 text-green-500"
                : snap.freshness === "STALE"
                  ? "border-yellow-500/40 text-yellow-500"
                  : "border-muted-foreground/30 text-muted-foreground"
            }`}
            title={snap.last_updated_at ? `Live quotes last updated: ${snap.last_updated_at.toLocaleString()}` : "Live quotes: no timestamp"}
          >
            <Timer className="h-3 w-3 mr-1" />
            {snap.freshness}
          </Badge>
        </div>
      </div>

      {snap.errors.length > 0 && (
        <div className="mb-3 rounded-md border border-destructive/30 bg-destructive/10 p-3">
          {snap.errors.slice(0, 2).map((e) => (
            <div key={e} className="text-xs text-destructive">
              {e}
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="bg-background/70 border border-white/10 rounded-md p-3">
          <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">
            Unrealized P&L
          </div>
          <div className={`number-mono text-lg font-bold ${pnlClass(snap.unrealized_pnl)}`}>
            {snap.unrealized_pnl >= 0 ? "+" : "-"}
            {formatUsd2(Math.abs(snap.unrealized_pnl))}
          </div>
        </div>

        <div className="bg-background/70 border border-white/10 rounded-md p-3">
          <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">
            Daily P&L
          </div>
          <div className={`flex items-center gap-1 number-mono text-lg font-bold ${pnlClass(snap.daily_pnl)}`}>
            {snap.daily_pnl > 0 ? <TrendingUp className="h-4 w-4" /> : snap.daily_pnl < 0 ? <TrendingDown className="h-4 w-4" /> : null}
            <span>
              {snap.daily_pnl >= 0 ? "+" : "-"}
              {formatUsd2(Math.abs(snap.daily_pnl))}
            </span>
          </div>
        </div>

        <div className="bg-background/70 border border-white/10 rounded-md p-3">
          <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">
            Drawdown %
          </div>
          <div className="number-mono text-lg font-bold text-foreground">
            {snap.drawdown_pct === null ? "—" : `${snap.drawdown_pct.toFixed(2)}%`}
          </div>
          <div className="text-[10px] text-muted-foreground mt-1">
            HWM-based (persisted daily)
          </div>
        </div>

        <div className="bg-background/70 border border-white/10 rounded-md p-3">
          <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">
            Open Positions
          </div>
          <div className="number-mono text-lg font-bold text-foreground">{snap.open_positions_count}</div>
          <div className="text-[10px] text-muted-foreground mt-1 truncate">
            {snap.open_positions.slice(0, 3).map((p) => p.symbol).join(", ") || "None"}
            {snap.open_positions_count > 3 ? "…" : ""}
          </div>
        </div>
      </div>
    </Card>
  );
}

