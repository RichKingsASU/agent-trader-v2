import { useEffect, useMemo, useRef, useState } from "react";
import { collection, limit, onSnapshot, orderBy, query } from "firebase/firestore";
import { db } from "@/firebase";
import { useAuth } from "@/contexts/AuthContext";
import { useMarketLiveQuotes } from "@/hooks/useMarketLiveQuotes";
import { useAlpacaAccountSnapshot } from "@/hooks/useAlpacaAccountSnapshot";

export interface PaperPosition {
  id: string;
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
  entry_price: number;
  current_price: number | null;
  unrealized_pnl: number;
}

export interface PaperTradingConfidence {
  open_positions: PaperPosition[];
  open_positions_count: number;
  unrealized_pnl: number;
  daily_pnl: number;
  drawdown_pct: number | null;
  base_equity_usd: number | null;
  synthetic_equity_usd: number | null;
  last_updated_at: Date | null;
  freshness: "LIVE" | "STALE" | "OFFLINE";
  errors: string[];
}

function coerceNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const s = value.trim();
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function todayKeyUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

function pct(n: number, d: number): number | null {
  if (!Number.isFinite(n) || !Number.isFinite(d) || d <= 0) return null;
  return (n / d) * 100;
}

function pickMidPrice(q: { bid_price?: number | null; ask_price?: number | null; last_trade_price?: number | null; price?: number | null }): number | null {
  const bid = typeof q.bid_price === "number" ? q.bid_price : null;
  const ask = typeof q.ask_price === "number" ? q.ask_price : null;
  if (bid !== null && ask !== null && bid > 0 && ask > 0) return (bid + ask) / 2;
  const last = typeof q.last_trade_price === "number" ? q.last_trade_price : null;
  if (last !== null && last > 0) return last;
  const px = typeof q.price === "number" ? q.price : null;
  if (px !== null && px > 0) return px;
  return null;
}

/**
 * Confidence snapshot for paper trading (shadow-mode):
 * - Open positions: `users/{uid}/shadowTradeHistory` where status==OPEN (derived client-side)
 * - Pricing: `tenants/{tenantId}/live_quotes` (mid/last) to recompute P&L frequently (<5s)
 *
 * Note: drawdown is computed vs a per-day persisted high-watermark (localStorage),
 * so it survives refresh but stays client/session-local.
 */
export function usePaperTradingConfidence(): PaperTradingConfidence {
  const { user, tenantId } = useAuth();
  const { quotesBySymbol, status: quoteStatus, lastUpdated } = useMarketLiveQuotes({
    subscribeQuotes: true,
    subscribeHeartbeat: true,
    heartbeatStaleAfterSeconds: 30,
  });
  const { snapshot: acctSnap } = useAlpacaAccountSnapshot();

  const [shadowTrades, setShadowTrades] = useState<Array<Record<string, unknown>>>([]);
  const [tradeError, setTradeError] = useState<string | null>(null);

  useEffect(() => {
    if (!user?.uid) {
      setShadowTrades([]);
      setTradeError(null);
      return;
    }

    // Query a bounded recent window; sufficient for "today" + open positions in operator dashboard.
    const ref = collection(db, "users", user.uid, "shadowTradeHistory");
    const q = query(ref, orderBy("created_at", "desc"), limit(250));
    const unsub = onSnapshot(
      q,
      (snap) => {
        const next: Array<Record<string, unknown>> = [];
        snap.forEach((d) => next.push({ id: d.id, ...((d.data() ?? {}) as Record<string, unknown>) }));
        setShadowTrades(next);
        setTradeError(null);
      },
      (err) => {
        console.error("Failed to subscribe shadowTradeHistory:", err);
        setShadowTrades([]);
        setTradeError(err?.message || "Failed to load shadow trades");
      },
    );
    return () => unsub();
  }, [user?.uid]);

  const errors = useMemo(() => {
    const out: string[] = [];
    if (!tenantId) out.push("Missing tenantId (live quote pricing unavailable).");
    if (tradeError) out.push(tradeError);
    return out;
  }, [tenantId, tradeError]);

  const computed = useMemo(() => {
    const open: PaperPosition[] = [];
    const today = todayKeyUtc();

    let unreal = 0;
    let realizedToday = 0;

    for (const t of shadowTrades) {
      const status = (typeof t.status === "string" ? t.status : "").toUpperCase();
      const symbol = (typeof t.symbol === "string" ? t.symbol : "").trim().toUpperCase();
      if (!symbol) continue;

      const rawSide = (typeof t.side === "string" ? t.side : "").toUpperCase();
      const side: "BUY" | "SELL" = rawSide === "SELL" ? "SELL" : "BUY";

      const qty = coerceNumber(t.quantity) ?? 0;
      const entry = coerceNumber(t.entry_price) ?? 0;

      const q = quotesBySymbol[symbol];
      const mark = q ? pickMidPrice(q) : null;

      // Prefer recomputed P&L off live quotes; fall back to stored `current_pnl` when marks are unavailable.
      const storedUnreal = coerceNumber(t.current_pnl) ?? 0;
      const computedUnreal = mark !== null ? (side === "BUY" ? (mark - entry) * qty : (entry - mark) * qty) : storedUnreal;

      if (status === "OPEN") {
        open.push({
          id: String(t.id ?? ""),
          symbol,
          side,
          quantity: qty,
          entry_price: entry,
          current_price: mark,
          unrealized_pnl: computedUnreal,
        });
        unreal += computedUnreal;
        continue;
      }

      if (status === "CLOSED") {
        const closedIso = typeof t.closed_at_iso === "string" ? t.closed_at_iso : null;
        if (closedIso && closedIso.slice(0, 10) === today) {
          const finalPnl = coerceNumber(t.final_pnl) ?? coerceNumber(t.current_pnl) ?? 0;
          realizedToday += finalPnl;
        }
      }
    }

    // Daily P&L = realized today + open unrealized (operator clarity during paper trading).
    const dailyPnl = realizedToday + unreal;

    // Base equity anchor (per-day, persisted client-side for stability).
    const baseEquity =
      typeof acctSnap?.equity === "number" && Number.isFinite(acctSnap.equity) && acctSnap.equity > 0 ? acctSnap.equity : null;

    const keyBase = user?.uid ? `paper_base_equity_usd:${user.uid}:${today}` : null;
    const keyHwm = user?.uid ? `paper_hwm_equity_usd:${user.uid}:${today}` : null;

    let baseEquityPersisted: number | null = null;
    if (keyBase && typeof window !== "undefined") {
      const raw = window.localStorage.getItem(keyBase);
      const n = raw ? Number(raw) : NaN;
      baseEquityPersisted = Number.isFinite(n) && n > 0 ? n : null;
    }
    if (!baseEquityPersisted && baseEquity && keyBase && typeof window !== "undefined") {
      window.localStorage.setItem(keyBase, String(baseEquity));
      baseEquityPersisted = baseEquity;
    }

    const syntheticEquity = baseEquityPersisted ? baseEquityPersisted + dailyPnl : null;

    let hwm: number | null = null;
    if (keyHwm && typeof window !== "undefined") {
      const raw = window.localStorage.getItem(keyHwm);
      const n = raw ? Number(raw) : NaN;
      hwm = Number.isFinite(n) && n > 0 ? n : null;
    }
    if (syntheticEquity !== null && keyHwm && typeof window !== "undefined") {
      const next = hwm === null ? syntheticEquity : Math.max(hwm, syntheticEquity);
      if (hwm === null || next !== hwm) window.localStorage.setItem(keyHwm, String(next));
      hwm = next;
    }

    const dd = syntheticEquity !== null && hwm !== null ? pct(hwm - syntheticEquity, hwm) : null;

    open.sort((a, b) => a.symbol.localeCompare(b.symbol));

    return {
      open_positions: open,
      open_positions_count: open.length,
      unrealized_pnl: unreal,
      daily_pnl: dailyPnl,
      drawdown_pct: dd,
      base_equity_usd: baseEquityPersisted,
      synthetic_equity_usd: syntheticEquity,
    };
  }, [acctSnap?.equity, quotesBySymbol, shadowTrades, user?.uid]);

  return {
    ...computed,
    last_updated_at: lastUpdated,
    freshness: quoteStatus,
    errors,
  };
}

