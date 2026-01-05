
import { useEffect, useMemo, useState } from "react";
import { doc, onSnapshot, query, Timestamp } from "firebase/firestore";
import { db } from "../firebase";

import { useAuth } from "@/contexts/AuthContext";
import { tenantCollection, tenantDoc } from "@/lib/tenancy/firestore";
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

export interface MarketIngestHeartbeat {
  raw: Record<string, unknown>;
  last_heartbeat_at: Date | null;
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
}

const CACHE_KEY = "agenttrader_cache";
const ZERO_FLICKER_GRACE_MS = 10_000;

function parseAlpacaNumber(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    // Alpaca commonly returns numeric fields as strings
    const n = Number(value.replace(/[$,]/g, "").trim());
    return Number.isFinite(n) ? n : 0;
  }
  return 0;
}

function readWarmCache(): Omit<LiveQuotesState, "loading"> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LiveQuotesState> | null;
    const equity = parseAlpacaNumber(parsed?.equity);
    const buyingPower = parseAlpacaNumber(parsed?.buyingPower);
    const cash = parseAlpacaNumber(parsed?.cash);
    return { equity, buyingPower, cash };
  } catch {
    return null;
  }
}

function writeWarmCache(next: Omit<LiveQuotesState, "loading">) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(next));
  } catch {
    // Ignore quota/private-mode write errors
  }
  return null;
}

export const useLiveQuotes = (options: UseLiveQuotesOptions = {}): UseLiveQuotesReturn => {
  const {
    subscribeQuotes = true,
    subscribeHeartbeat = true,
    heartbeatStaleAfterSeconds = 30,
  } = options;

  useEffect(() => {
    if (!subscribeHeartbeat) return;
    if (!tenantId) return;

    setError((prev) => prev); // no-op; keep prior quote error if any

    const ref = tenantDoc(db, tenantId, "ops", "market_ingest");
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

    return () => {
      unsubscribe();
    };
  }, []);

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

// --- Alpaca account snapshot (warm-cache + live listener via Zustand store) ---
export interface UseLiveAccountReturn {
  equity: number;
  buying_power: number;
  cash: number;
  updatedAt: Date | null;
  hasCache: boolean;
  loading: boolean;
  listenerStatus: "idle" | "connecting" | "connected" | "error";
  listenerError: string | null;
}

export const useLiveAccount = (): UseLiveAccountReturn => {
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
  const loading = !hasHydrated && !hasCache && listenerStatus !== "connected";

  return {
    equity,
    buyingPower: buying_power,
    cash,
    updatedAt,
    loading,
    hasCache,
    error: listenerError,
  };
};

// --- Warm Cache listener for Alpaca account snapshot (dashboard balances) ---
const ACCOUNT_SNAPSHOT_HOLD_ZERO_MS = 10_000;

function parseAlpacaNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const s = value.trim();
  if (!s) return null;
  const normalized = s.replaceAll(",", "");
  const n = Number(normalized);
  return Number.isFinite(n) ? n : null;
}

function pickAlpacaNumber(raw: Record<string, unknown>, ...keys: string[]): number | null {
  for (const k of keys) {
    const v = parseAlpacaNumber(raw[k]);
    if (v !== null) return v;
  }
  return null;
}

/**
 * Starts a Firestore listener on `alpacaAccounts/snapshot` and updates the warm-cache store.
 *
 * Flicker-guard: if Firestore temporarily emits empty data or "0" strings, we keep the last
 * cached value for 10s to avoid a "$0" UI flash during reconnect/redeploy windows.
 */
export const useLiveAccountListener = (): void => {
  const setAccount = useAccountStore((s) => s.setAccount);
  const setListenerStatus = useAccountStore((s) => s.setListenerStatus);

  const lastRawRef = useRef<Record<string, unknown>>({});

  const equityHoldStartMsRef = useRef<number | null>(null);
  const buyingPowerHoldStartMsRef = useRef<number | null>(null);

  const equityHoldTimerRef = useRef<number | null>(null);
  const buyingPowerHoldTimerRef = useRef<number | null>(null);

  const applyFromRaw = (raw: Record<string, unknown>) => {
    const now = Date.now();
    lastRawRef.current = raw;

    // Read current values from the store without causing re-renders.
    const { equity: prevEquity, buying_power: prevBuyingPower } = useAccountStore.getState();

    const nextPartial: Record<string, unknown> = {};

    const nextEquity =
      pickAlpacaNumber(raw, "equity") ??
      (raw.raw && typeof raw.raw === "object" ? pickAlpacaNumber(raw.raw as Record<string, unknown>, "equity") : null);
    const nextBuyingPower =
      pickAlpacaNumber(raw, "buying_power", "buyingPower") ??
      (raw.raw && typeof raw.raw === "object"
        ? pickAlpacaNumber(raw.raw as Record<string, unknown>, "buying_power", "buyingPower")
        : null);
    const nextCash =
      pickAlpacaNumber(raw, "cash", "cash_balance", "cashBalance", "settled_cash", "settledCash") ??
      (raw.raw && typeof raw.raw === "object"
        ? pickAlpacaNumber(
            raw.raw as Record<string, unknown>,
            "cash",
            "cash_balance",
            "cashBalance",
            "settled_cash",
            "settledCash",
          )
        : null);

    const updatedAt =
      coerceDate(raw.syncedAt) ??
      coerceDate(raw.updated_at) ??
      coerceDate(raw.updatedAt) ??
      coerceDate(raw.updated_at_iso) ??
      coerceDate(raw.updatedAtIso) ??
      (raw.raw && typeof raw.raw === "object"
        ? coerceDate((raw.raw as Record<string, unknown>).syncedAt) ??
          coerceDate((raw.raw as Record<string, unknown>).updated_at) ??
          coerceDate((raw.raw as Record<string, unknown>).updatedAt) ??
          coerceDate((raw.raw as Record<string, unknown>).updated_at_iso) ??
          coerceDate((raw.raw as Record<string, unknown>).updatedAtIso)
        : null);

    if (updatedAt) {
      nextPartial.updated_at_ms = updatedAt.getTime();
    }

    // Equity: hold previous if we see 0 or missing (temporarily) for up to 10s.
    if (typeof nextEquity === "number") {
      if (nextEquity === 0 && prevEquity > 0) {
        const holdStart = equityHoldStartMsRef.current;
        if (holdStart === null) {
          equityHoldStartMsRef.current = now;
          if (equityHoldTimerRef.current !== null) window.clearTimeout(equityHoldTimerRef.current);
          equityHoldTimerRef.current = window.setTimeout(() => applyFromRaw(lastRawRef.current), ACCOUNT_SNAPSHOT_HOLD_ZERO_MS);
          // omit update during hold
        } else if (now - holdStart >= ACCOUNT_SNAPSHOT_HOLD_ZERO_MS) {
          nextPartial.equity = nextEquity;
          equityHoldStartMsRef.current = null;
        }
      } else {
        nextPartial.equity = nextEquity;
        equityHoldStartMsRef.current = null;
      }
    } else {
      // missing/empty: hold for 10s (do not overwrite cache)
      if (equityHoldStartMsRef.current === null) {
        equityHoldStartMsRef.current = now;
        if (equityHoldTimerRef.current !== null) window.clearTimeout(equityHoldTimerRef.current);
        equityHoldTimerRef.current = window.setTimeout(() => applyFromRaw(lastRawRef.current), ACCOUNT_SNAPSHOT_HOLD_ZERO_MS);
      }
    }

    // Buying power: same hold semantics.
    if (typeof nextBuyingPower === "number") {
      if (nextBuyingPower === 0 && prevBuyingPower > 0) {
        const holdStart = buyingPowerHoldStartMsRef.current;
        if (holdStart === null) {
          buyingPowerHoldStartMsRef.current = now;
          if (buyingPowerHoldTimerRef.current !== null) window.clearTimeout(buyingPowerHoldTimerRef.current);
          buyingPowerHoldTimerRef.current = window.setTimeout(
            () => applyFromRaw(lastRawRef.current),
            ACCOUNT_SNAPSHOT_HOLD_ZERO_MS,
          );
          // omit update during hold
        } else if (now - holdStart >= ACCOUNT_SNAPSHOT_HOLD_ZERO_MS) {
          nextPartial.buying_power = nextBuyingPower;
          buyingPowerHoldStartMsRef.current = null;
        }
      } else {
        nextPartial.buying_power = nextBuyingPower;
        buyingPowerHoldStartMsRef.current = null;
      }
    } else {
      if (buyingPowerHoldStartMsRef.current === null) {
        buyingPowerHoldStartMsRef.current = now;
        if (buyingPowerHoldTimerRef.current !== null) window.clearTimeout(buyingPowerHoldTimerRef.current);
        buyingPowerHoldTimerRef.current = window.setTimeout(
          () => applyFromRaw(lastRawRef.current),
          ACCOUNT_SNAPSHOT_HOLD_ZERO_MS,
        );
      }
    }

    if (typeof nextCash === "number") {
      nextPartial.cash = nextCash;
    }

    // Only write if there's something to update; avoids useless re-renders.
    if (Object.keys(nextPartial).length > 0) {
      setAccount(nextPartial);
    }
  };

  useEffect(() => {
    if (authLoading || !tenantId) return;
    store.startAccountListener(tenantId);
  }, [authLoading, tenantId, store.startAccountListener]);

  const updatedAt = store.updatedAtMs ? new Date(store.updatedAtMs) : null;
  const hasCache = store.equity !== 0 || store.buying_power !== 0 || store.cash !== 0 || store.updatedAtMs !== null;
  const loading =
    authLoading || (!store.hasHydrated && !hasCache && store.listenerStatus !== "connected" && store.listenerStatus !== "error");

  return {
    equity: store.equity,
    buying_power: store.buying_power,
    cash: store.cash,
    updatedAt,
    hasCache,
    loading,
    listenerStatus: store.listenerStatus,
    listenerError: store.listenerError,
  };
};
