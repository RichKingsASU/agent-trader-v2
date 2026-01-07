import { useMemo } from "react";

import { useMarketLiveQuotes } from "@/hooks/useMarketLiveQuotes";
import { useAccountStore } from "@/store/useAccountStore";

export type LiveStatus = "LIVE" | "STALE" | "OFFLINE";

export interface UseLiveQuotesOptions {
  subscribeQuotes?: boolean;
  subscribeHeartbeat?: boolean;
  heartbeatStaleAfterSeconds?: number;
}

export interface UseLiveQuotesReturn {
  // Market quotes (live_quotes)
  quotes: ReturnType<typeof useMarketLiveQuotes>["quotes"];
  quotesBySymbol: ReturnType<typeof useMarketLiveQuotes>["quotesBySymbol"];
  loading: boolean;
  error: string | null;
  heartbeat: ReturnType<typeof useMarketLiveQuotes>["heartbeat"];
  heartbeatAt: ReturnType<typeof useMarketLiveQuotes>["heartbeatAt"];
  status: LiveStatus;
  isLive: boolean;
  lastUpdated: ReturnType<typeof useMarketLiveQuotes>["lastUpdated"];

  // Account snapshot (warm-cache only in pre-Firebase stabilization)
  equity: number;
  buyingPower: number;
  cash: number;
}

/**
 * Pre-Firebase stabilization wrapper:
 * - Keeps the existing `useLiveQuotes` API shape used throughout the UI
 * - Uses `useMarketLiveQuotes` for market ingest status/quotes (if available)
 * - Exposes cached account numbers from the local store (no external SaaS required)
 */
export function useLiveQuotes(options: UseLiveQuotesOptions = {}): UseLiveQuotesReturn {
  const market = useMarketLiveQuotes({
    subscribeQuotes: options.subscribeQuotes,
    subscribeHeartbeat: options.subscribeHeartbeat,
    heartbeatStaleAfterSeconds: options.heartbeatStaleAfterSeconds,
  });

  const { equity, buying_power, cash } = useAccountStore((s) => ({
    equity: s.equity,
    buying_power: s.buying_power,
    cash: s.cash,
  }));

  return {
    ...market,
    status: market.status as LiveStatus,
    equity,
    buyingPower: buying_power,
    cash,
  };
}

export interface UseLiveAccountReturn {
  equity: number;
  buying_power: number;
  buyingPower: number;
  cash: number;
  updatedAt: Date | null;
  hasCache: boolean;
  loading: boolean;
  listenerStatus: "idle" | "connecting" | "connected" | "error";
  listenerError: string | null;
}

/**
 * Lightweight account snapshot hook (warm-cache only).
 * This intentionally avoids any external SaaS dependency pre-Firebase.
 */
export function useLiveAccount(): UseLiveAccountReturn {
  const { equity, buying_power, cash, updated_at_ms, hasWarmCache, hasHydrated, listenerStatus, listenerError } =
    useAccountStore((s) => ({
      equity: s.equity,
      buying_power: s.buying_power,
      cash: s.cash,
      updated_at_ms: s.updated_at_ms,
      hasWarmCache: s.hasWarmCache,
      hasHydrated: s.hasHydrated,
      listenerStatus: s.listenerStatus,
      listenerError: s.listenerError,
    }));

  const updatedAt = typeof updated_at_ms === "number" ? new Date(updated_at_ms) : null;
  const hasAny = equity !== 0 || buying_power !== 0 || cash !== 0 || updatedAt !== null;
  const hasCache = hasWarmCache || hasAny;
  const loading = useMemo(() => !hasHydrated && !hasCache && listenerStatus !== "connected", [hasHydrated, hasCache, listenerStatus]);

  return {
    equity,
    buying_power,
    buyingPower: buying_power,
    cash,
    updatedAt,
    hasCache,
    loading,
    listenerStatus,
    listenerError,
  };
}

