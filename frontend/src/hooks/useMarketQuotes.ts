import { useEffect, useMemo, useState } from "react";
import { query, Timestamp, onSnapshot } from "firebase/firestore";
import { db } from "@/firebase";
import { useAuth } from "@/contexts/AuthContext";
import { tenantCollection, tenantDoc } from "@/lib/tenancy/firestore";

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

export interface MarketIngestHeartbeat {
  raw: Record<string, unknown>;
  last_heartbeat_at: Date | null;
}

export interface UseMarketQuotesOptions {
  subscribeQuotes?: boolean;
  subscribeHeartbeat?: boolean;
  heartbeatStaleAfterSeconds?: number;
}

export interface UseMarketQuotesReturn {
  quotes: LiveQuote[];
  quotesBySymbol: LiveQuotesBySymbol;
  loading: boolean;
  error: string | null;
  heartbeat: MarketIngestHeartbeat | null;
  heartbeatAt: Date | null;
  status: LiveStatus;
  isLive: boolean;
  lastUpdated: Date | null;
}

function coerceDate(value: unknown): Date | null {
  if (!value) return null;
  if (value instanceof Date && Number.isFinite(value.getTime())) return value;
  if (value instanceof Timestamp) {
    try {
      const d = value.toDate();
      return d instanceof Date && Number.isFinite(d.getTime()) ? d : null;
    } catch {
      return null;
    }
  }

  if (typeof value === "object" && value !== null) {
    const rec = value as Record<string, unknown>;
    if (typeof rec.toDate === "function") {
      try {
        const d = (rec.toDate as () => unknown)();
        return d instanceof Date && Number.isFinite(d.getTime()) ? d : null;
      } catch {
        return null;
      }
    }
    if (typeof rec.seconds === "number") {
      const ms = rec.seconds * 1000;
      const d = new Date(ms);
      return Number.isFinite(d.getTime()) ? d : null;
    }
  }

  if (typeof value === "number" && Number.isFinite(value)) {
    // seconds vs millis
    const ms = value < 10_000_000_000 ? value * 1000 : value;
    const d = new Date(ms);
    return Number.isFinite(d.getTime()) ? d : null;
  }

  if (typeof value === "string") {
    const t = Date.parse(value);
    if (!Number.isFinite(t)) return null;
    const d = new Date(t);
    return Number.isFinite(d.getTime()) ? d : null;
  }

  return null;
}

function normalizeSymbol(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const s = value.trim().toUpperCase();
  return s.length > 0 ? s : null;
}

function maxDate(a: Date | null, b: Date | null): Date | null {
  if (!a) return b;
  if (!b) return a;
  return a > b ? a : b;
}

function pickHeartbeatAt(raw: Record<string, unknown>): Date | null {
  return (
    coerceDate(raw.last_heartbeat_at) ??
    coerceDate(raw.last_heartbeat) ??
    coerceDate(raw.lastHeartbeatAt) ??
    coerceDate(raw.lastHeartbeat) ??
    coerceDate(raw.updated_at) ??
    coerceDate(raw.updatedAt) ??
    coerceDate(raw.ts) ??
    coerceDate(raw.timestamp) ??
    null
  );
}

function pickQuoteUpdatedAt(raw: Record<string, unknown>): Date | null {
  return (
    coerceDate(raw.last_update_ts) ??
    coerceDate(raw.lastUpdateTs) ??
    coerceDate(raw.updated_at) ??
    coerceDate(raw.updatedAt) ??
    coerceDate(raw.ts) ??
    coerceDate(raw.timestamp) ??
    null
  );
}

function coerceNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function pickNumber(raw: Record<string, unknown>, ...keys: string[]): number | null {
  for (const k of keys) {
    const v = coerceNumber(raw[k]);
    if (v !== null) return v;
  }
  return null;
}

export const useMarketQuotes = (options: UseMarketQuotesOptions = {}): UseMarketQuotesReturn => {
  const {
    subscribeQuotes = true,
    subscribeHeartbeat = true,
    heartbeatStaleAfterSeconds = 30,
  } = options;

  const [quotesBySymbol, setQuotesBySymbol] = useState<LiveQuotesBySymbol>({});
  const [heartbeat, setHeartbeat] = useState<MarketIngestHeartbeat | null>(null);
  const [status, setStatus] = useState<LiveStatus>("OFFLINE");
  const [loading, setLoading] = useState<boolean>(subscribeQuotes);
  const [error, setError] = useState<string | null>(null);
  const { tenantId } = useAuth();

  // Quotes: subscribe to collection live_quotes
  useEffect(() => {
    if (!subscribeQuotes) {
      setLoading(false);
      return;
    }
    if (!tenantId) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    const q = query(tenantCollection(db!, tenantId, "market_intelligence", "quotes", "live"));
    const unsubscribe = onSnapshot(
      q,
      (querySnapshot) => {
        const next: LiveQuotesBySymbol = {};

        querySnapshot.forEach((snap) => {
          const raw = snap.data() as Record<string, unknown>;
          const symbol = normalizeSymbol(raw.symbol) ?? normalizeSymbol(snap.id) ?? "UNKNOWN";
          const updatedAt = pickQuoteUpdatedAt(raw);

          next[symbol] = {
            symbol,
            // Back-compat:
            // - canonical ingest path currently writes bid/ask/ts
            // - some legacy paths (or SQL mirrors) use bid_price/ask_price/last_trade_price
            bid_price: pickNumber(raw, "bid_price", "bid"),
            ask_price: pickNumber(raw, "ask_price", "ask"),
            last_trade_price: pickNumber(raw, "last_trade_price", "last", "last_price"),
            price: pickNumber(raw, "price", "mid"),
            source: typeof raw.source === "string" ? raw.source : null,
            last_update_ts: updatedAt,
          };
        });

        setQuotesBySymbol(next);
        setLoading(false);
      },
      (err) => {
        console.error("Error fetching live quotes:", err);
        setError("Failed to load live quotes");
        setLoading(false);
      },
    );

    return () => unsubscribe();
  }, [subscribeQuotes, tenantId]);

  // Heartbeat: subscribe to ops/market_ingest doc
  useEffect(() => {
    if (!subscribeHeartbeat) return;
    if (!tenantId) return;
    // Assuming 'db' is available in scope, e.g., from a context or global import
    if (!db) {
      return; // Do not set error here, as it might override a quote error
    }

    setError((prev) => prev); // no-op; keep prior quote error if any

    const ref = tenantDoc(db!, tenantId, "ops", "market_ingest");
    const unsubscribe = onSnapshot(
      ref,
      (snap) => {
        const raw = (snap.exists() ? (snap.data() as Record<string, unknown>) : {}) as Record<string, unknown>;
        setHeartbeat({
          raw,
          last_heartbeat_at: pickHeartbeatAt(raw),
        });
      },
      (err) => {
        console.error("Error fetching market ingest heartbeat:", err);
        setHeartbeat(null);
      },
    );

    return () => unsubscribe();
  }, [subscribeHeartbeat, tenantId]);

  // Derive LIVE/STALE/OFFLINE from heartbeat freshness (updates over time).
  useEffect(() => {
    const compute = () => {
      // Treat "freshness" as the most recent timestamp across the heartbeat and
      // the quote updates we’ve observed. This avoids showing OFFLINE if quotes
      // are flowing but the heartbeat doc is missing/mis-shaped, and it also
      // avoids showing LIVE when quotes have gone stale.
      let maxQuoteUpdatedAt: Date | null = null;
      if (subscribeQuotes) {
        for (const q of Object.values(quotesBySymbol)) {
          maxQuoteUpdatedAt = maxDate(maxQuoteUpdatedAt, q.last_update_ts ?? null);
        }
      }

      const hbAt = subscribeHeartbeat ? (heartbeat?.last_heartbeat_at ?? null) : null;
      const effectiveAt = maxDate(maxQuoteUpdatedAt, hbAt);

      if (!effectiveAt) {
        setStatus("OFFLINE");
        return;
      }

      const ageSec = (Date.now() - effectiveAt.getTime()) / 1000;
      setStatus(ageSec <= heartbeatStaleAfterSeconds ? "LIVE" : "STALE");
    };

    compute();
    const interval = setInterval(compute, 5000);
    return () => clearInterval(interval);
  }, [heartbeat, heartbeatStaleAfterSeconds, quotesBySymbol, subscribeHeartbeat, subscribeQuotes]);

  const quotes = useMemo(() => {
    return Object.values(quotesBySymbol).sort((a, b) => a.symbol.localeCompare(b.symbol));
  }, [quotesBySymbol]);

  const heartbeatAt = heartbeat?.last_heartbeat_at ?? null;
  const isLive = status === "LIVE";

  const lastUpdated = useMemo(() => {
    let maxQuoteUpdatedAt: Date | null = null;
    for (const q of Object.values(quotesBySymbol)) {
      maxQuoteUpdatedAt = maxDate(maxQuoteUpdatedAt, q.last_update_ts ?? null);
    }
    return maxDate(maxQuoteUpdatedAt, heartbeatAt);
  }, [quotesBySymbol, heartbeatAt]);

  return { quotes, quotesBySymbol, loading, error, heartbeat, heartbeatAt, status, isLive, lastUpdated };
};

