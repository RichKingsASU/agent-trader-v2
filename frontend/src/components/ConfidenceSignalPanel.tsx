import React, { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useUserTrading } from "@/contexts/UserTradingContext";
import { TrendingDown, TrendingUp, RefreshCw, ShieldCheck } from "lucide-react";

type SnapshotNumber = string | number | undefined | null;

function asNumber(v: SnapshotNumber): number | null {
  if (v === undefined || v === null) return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  const s = String(v).trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function formatUsd(value: number | null): string {
  const v = value ?? 0;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(v);
}

function formatPct(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(2)}%`;
}

/**
 * ConfidenceSignalPanel
 *
 * Operator-facing “immediate clarity” panel for paper/shadow trading.
 * Refreshes every 5s to update drawdown + timestamps (underlying Firestore listeners are realtime).
 */
export const ConfidenceSignalPanel: React.FC = () => {
  const { accountSnapshot, openShadowTrades, totalUnrealizedPnL } = useUserTrading();
  const [tick, setTick] = useState(0);
  const [sessionHwmEquity, setSessionHwmEquity] = useState<number | null>(null);
  const [sessionDrawdownPct, setSessionDrawdownPct] = useState<number | null>(null);
  const lastTickAt = useRef<number>(Date.now());

  const account = (accountSnapshot?.account ?? {}) as Record<string, any>;
  const raw = (accountSnapshot?.raw ?? {}) as Record<string, any>;

  const equity = useMemo(() => {
    return asNumber(accountSnapshot?.equity) ?? asNumber(account?.equity) ?? asNumber(raw?.equity);
  }, [accountSnapshot?.equity, account?.equity, raw?.equity]);

  const dailyPnl = useMemo(() => {
    const lastEquity = asNumber(account?.last_equity) ?? asNumber(raw?.last_equity);
    if (equity === null || lastEquity === null || lastEquity <= 0) return null;
    return equity - lastEquity;
  }, [equity, account?.last_equity, raw?.last_equity]);

  // 5s UI refresh loop (keeps drawdown/current timestamp “fresh” even if equity updates slower)
  useEffect(() => {
    const id = window.setInterval(() => {
      lastTickAt.current = Date.now();
      setTick((t) => t + 1);
    }, 5000);
    return () => window.clearInterval(id);
  }, []);

  // Track session high-water mark & session drawdown, updated on each tick.
  useEffect(() => {
    if (equity === null) return;
    setSessionHwmEquity((prev) => {
      const nextHwm = prev === null ? equity : Math.max(prev, equity);
      const dd = nextHwm > 0 ? Math.max(0, (nextHwm - equity) / nextHwm) * 100 : 0;
      setSessionDrawdownPct(dd);
      return nextHwm;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [equity, tick]);

  const pnlColor = totalUnrealizedPnL >= 0 ? "text-green-500" : "text-red-500";
  const pnlIcon =
    totalUnrealizedPnL >= 0 ? (
      <TrendingUp className="h-5 w-5 text-green-500" />
    ) : (
      <TrendingDown className="h-5 w-5 text-red-500" />
    );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5" />
              Confidence Snapshot (Paper Trading)
            </CardTitle>
            <CardDescription>
              Open positions, P&amp;L, and drawdown. Auto-refresh &lt; 5s.
            </CardDescription>
          </div>
          <Badge variant="outline" className="flex items-center gap-2">
            <RefreshCw className="h-3 w-3" />
            5s
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="space-y-1">
            <p className="text-sm text-muted-foreground">Open Positions</p>
            <p className="text-2xl font-bold">{openShadowTrades.length}</p>
            <p className="text-xs text-muted-foreground">Source: `users/{`{uid}`}/shadowTradeHistory`</p>
          </div>

          <div className="space-y-1">
            <p className="text-sm text-muted-foreground flex items-center gap-2">
              {pnlIcon} Unrealized P&amp;L
            </p>
            <p className={`text-2xl font-bold ${pnlColor}`}>{formatUsd(totalUnrealizedPnL)}</p>
            <p className="text-xs text-muted-foreground">Source: OPEN shadow trades `current_pnl`</p>
          </div>

          <div className="space-y-1">
            <p className="text-sm text-muted-foreground">Daily P&amp;L</p>
            <p className={`text-2xl font-bold ${(dailyPnl ?? 0) >= 0 ? "text-green-500" : "text-red-500"}`}>
              {dailyPnl === null ? "—" : formatUsd(dailyPnl)}
            </p>
            <p className="text-xs text-muted-foreground">
              Source: `users/{`{uid}`}/data/snapshot` (equity - last_equity)
            </p>
          </div>

          <div className="space-y-1">
            <p className="text-sm text-muted-foreground">Drawdown %</p>
            <p className="text-2xl font-bold">{formatPct(sessionDrawdownPct)}</p>
            <p className="text-xs text-muted-foreground">
              Session HWM: {sessionHwmEquity === null ? "—" : formatUsd(sessionHwmEquity)}
            </p>
          </div>
        </div>

        <div className="mt-4 pt-4 border-t text-xs text-muted-foreground">
          Last refresh: {new Date(lastTickAt.current).toLocaleTimeString()} · API snapshot:{" "}
          <span className="font-mono">GET /ops/confidence_snapshot</span>
        </div>
      </CardContent>
    </Card>
  );
};

