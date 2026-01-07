import { useMemo } from "react";
import { useAccountStore } from "@/store/useAccountStore";

export type LiveStatus = "LIVE" | "STALE" | "OFFLINE";

export interface LiveQuote {
  symbol: string;
  bid_price?: number | null;
  ask_price?: number | null;
  last_trade_price?: number | null;
  price?: number | null;
  source?: string | null;
  last_update_ts?: Date | null;
}

export interface LiveQuotesBySymbol {
  [symbol: string]: LiveQuote;
}

export interface UseLiveQuotesOptions {
  subscribeQuotes?: boolean;
  subscribeHeartbeat?: boolean;
  heartbeatStaleAfterSeconds?: number;
}

export interface UseLiveQuotesReturn {
  quotes: LiveQuote[];
  quotesBySymbol: LiveQuotesBySymbol;
  loading: boolean;
  error: string | null;
  status: LiveStatus;
  heartbeatAt: Date | null;
  lastUpdated: Date | null;
  isLive: boolean;

  // Convenience fields used by some pages/headers.
  equity: number;
}

/**
 * Minimal, safe live-quotes hook.
 *
 * This repo’s UI expects `useLiveQuotes()` to exist even when real-time ingest
 * isn’t configured yet. For Firebase Hosting + Auth migration, we keep this
 * hook read-only and stable: it returns cached account numbers from
 * `useAccountStore` and marks ingest as OFFLINE.
 */
export const useLiveQuotes = (_options: UseLiveQuotesOptions = {}): UseLiveQuotesReturn => {
  const { equity } = useAccountStore((s) => ({ equity: s.equity }));

  const quotesBySymbol = useMemo<LiveQuotesBySymbol>(() => ({}), []);
  const quotes = useMemo<LiveQuote[]>(() => [], []);

  const status: LiveStatus = "OFFLINE";
  const heartbeatAt: Date | null = null;
  const lastUpdated: Date | null = null;

  return {
    quotes,
    quotesBySymbol,
    loading: false,
    error: null,
    status,
    heartbeatAt,
    lastUpdated,
    isLive: false,
    equity,
  };
};

