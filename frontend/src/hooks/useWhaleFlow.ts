import { useEffect, useState } from "react";
import { query, Timestamp, onSnapshot, orderBy, limit } from "firebase/firestore";
import { db } from "../firebase";
import { useAuth } from "@/contexts/AuthContext";
import { tenantCollection } from "@/lib/tenancy/firestore";

export interface OptionsFlowTrade {
  id: string;
  symbol: string;
  strike: number;
  expiry: string;
  expiry_date: Date | null;
  days_to_expiry: number;
  option_type: "call" | "put";
  side: "buy" | "sell";
  execution_side: "ask" | "bid" | "mid";
  size: number;
  premium: number;
  underlying_price: number;
  iv: number;
  delta: number;
  gamma: number;
  moneyness: "ITM" | "ATM" | "OTM";
  otm_percentage: number;
  sentiment: "bullish" | "bearish" | "neutral";
  is_golden_sweep: boolean;
  timestamp: Date | null;
}

export interface SystemStatus {
  net_gex: number;
  volatility_bias: "Bullish" | "Bearish" | "Neutral";
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
    if ("toDate" in value && typeof (value as { toDate?: unknown }).toDate === "function") {
      try {
        const d = (value as { toDate: () => unknown }).toDate();
        return d instanceof Date && Number.isFinite(d.getTime()) ? d : null;
      } catch {
        return null;
      }
    }
    if ("seconds" in value && typeof (value as { seconds?: unknown }).seconds === "number") {
      const ms = (value as { seconds: number }).seconds * 1000;
      const d = new Date(ms);
      return Number.isFinite(d.getTime()) ? d : null;
    }
  }

  if (typeof value === "number" && Number.isFinite(value)) {
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

function coerceNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function calculateDaysToExpiry(expiryDate: Date | null): number {
  if (!expiryDate) return 0;
  const now = new Date();
  const diffTime = expiryDate.getTime() - now.getTime();
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
  return Math.max(0, diffDays);
}

function calculateOTMPercentage(
  strike: number,
  underlyingPrice: number,
  optionType: "call" | "put"
): number {
  if (optionType === "call") {
    return ((strike - underlyingPrice) / underlyingPrice) * 100;
  } else {
    return ((underlyingPrice - strike) / underlyingPrice) * 100;
  }
}

function determineMoneyness(
  strike: number,
  underlyingPrice: number,
  optionType: "call" | "put"
): "ITM" | "ATM" | "OTM" {
  const threshold = 0.02; // 2% threshold for ATM
  const ratio = strike / underlyingPrice;
  
  if (Math.abs(ratio - 1) < threshold) return "ATM";
  
  if (optionType === "call") {
    return strike > underlyingPrice ? "OTM" : "ITM";
  } else {
    return strike < underlyingPrice ? "OTM" : "ITM";
  }
}

function determineSentiment(
  optionType: "call" | "put",
  side: "buy" | "sell"
): "bullish" | "bearish" | "neutral" {
  if (optionType === "call" && side === "buy") return "bullish";
  if (optionType === "put" && side === "buy") return "bearish";
  if (optionType === "call" && side === "sell") return "bearish";
  if (optionType === "put" && side === "sell") return "bullish";
  return "neutral";
}

export function useWhaleFlow(maxTrades: number = 100) {
  const [trades, setTrades] = useState<OptionsFlowTrade[]>([]);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { tenantId } = useAuth();

  // Subscribe to options flow
  useEffect(() => {
    if (!tenantId) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    const q = query(
      tenantCollection(db, tenantId, "market_intelligence", "options_flow", "live"),
      orderBy("timestamp", "desc"),
      limit(maxTrades)
    );

    const unsubscribe = onSnapshot(
      q,
      (querySnapshot) => {
        const flowTrades: OptionsFlowTrade[] = [];

        querySnapshot.forEach((snap) => {
          const raw = snap.data() as Record<string, unknown>;
          
          const strike = coerceNumber(raw.strike) ?? 0;
          const underlyingPrice = coerceNumber(raw.underlying_price) ?? 0;
          const premium = coerceNumber(raw.premium) ?? 0;
          const size = coerceNumber(raw.size) ?? 0;
          const optionType = (typeof raw.option_type === "string" ? raw.option_type.toLowerCase() : "call") as "call" | "put";
          const side = (typeof raw.side === "string" ? raw.side.toLowerCase() : "buy") as "buy" | "sell";
          const executionSide = (typeof raw.execution_side === "string" ? raw.execution_side.toLowerCase() : "mid") as "ask" | "bid" | "mid";
          const expiryDate = coerceDate(raw.expiry_date);
          const daysToExpiry = coerceNumber(raw.days_to_expiry) ?? calculateDaysToExpiry(expiryDate);
          
          const moneyness = determineMoneyness(strike, underlyingPrice, optionType);
          const otmPercentage = calculateOTMPercentage(strike, underlyingPrice, optionType);
          const sentiment = determineSentiment(optionType, side);
          
          // Golden Sweep: >$1M premium and <14 days to expiry
          const isGoldenSweep = premium > 1_000_000 && daysToExpiry < 14 && daysToExpiry > 0;

          flowTrades.push({
            id: snap.id,
            symbol: typeof raw.symbol === "string" ? raw.symbol : "UNKNOWN",
            strike,
            expiry: typeof raw.expiry === "string" ? raw.expiry : "",
            expiry_date: expiryDate,
            days_to_expiry: daysToExpiry,
            option_type: optionType,
            side,
            execution_side: executionSide,
            size,
            premium,
            underlying_price: underlyingPrice,
            iv: coerceNumber(raw.iv) ?? 0,
            delta: coerceNumber(raw.delta) ?? 0,
            gamma: coerceNumber(raw.gamma) ?? 0,
            moneyness,
            otm_percentage: otmPercentage,
            sentiment,
            is_golden_sweep: isGoldenSweep,
            timestamp: coerceDate(raw.timestamp),
          });
        });

        setTrades(flowTrades);
        setLoading(false);
      },
      (err) => {
        console.error("Error fetching options flow:", err);
        setError("Failed to load options flow data");
        setLoading(false);
      }
    );

    return () => unsubscribe();
  }, [tenantId, maxTrades]);

  // Subscribe to system status for GEX data
  useEffect(() => {
    if (!tenantId) return;

    const statusRef = tenantCollection(db, tenantId, "ops");
    const q = query(statusRef, limit(1));

    const unsubscribe = onSnapshot(
      q,
      (querySnapshot) => {
        if (!querySnapshot.empty) {
          const raw = querySnapshot.docs[0].data() as Record<string, unknown>;
          setSystemStatus({
            net_gex: coerceNumber(raw.net_gex) ?? 0,
            volatility_bias: (typeof raw.volatility_bias === "string" 
              ? raw.volatility_bias 
              : "Neutral") as "Bullish" | "Bearish" | "Neutral",
          });
        }
      },
      (err) => {
        console.error("Error fetching system status:", err);
      }
    );

    return () => unsubscribe();
  }, [tenantId]);

  return { trades, systemStatus, loading, error };
}
