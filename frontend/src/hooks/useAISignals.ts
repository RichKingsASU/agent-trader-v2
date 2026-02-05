import { useState, useCallback, useEffect } from "react";
import { getFunctions, httpsCallable } from "firebase/functions";
import { app } from "@/firebase";

const SIGNAL_CACHE_KEY = "agenttrader_last_signal";

export interface TradingSignal {
  id?: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number;
  reasoning: string;
  target_allocation: number;
  timestamp?: any;
  account_snapshot?: {
    equity: string;
    buying_power: string;
    cash: string;
  };
}

interface UseAISignalsReturn {
  signal: TradingSignal | null;
  loading: boolean;
  error: string | null;
  generateSignal: () => Promise<void>;
}

/**
 * Custom hook to fetch AI-generated trading signals from Firebase Functions.
 * 
 * Phase 2: Signal Intelligence Integration with Warm Cache
 * 
 * Uses localStorage to show the last signal immediately on mount,
 * preventing UI flickering during API calls.
 */
export const useAISignals = (): UseAISignalsReturn => {
  const [signal, setSignal] = useState<TradingSignal | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Warm Cache: Load last signal from localStorage on mount
  useEffect(() => {
    try {
      const cached = localStorage.getItem(SIGNAL_CACHE_KEY);
      if (cached) {
        const parsedSignal = JSON.parse(cached) as TradingSignal;
        setSignal(parsedSignal);
      }
    } catch (err) {
      console.warn("Failed to load cached signal:", err);
    }
  }, []);

  const generateSignal = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const functions = getFunctions(app!);
      const generateTradingSignal = httpsCallable<unknown, TradingSignal>(
        functions,
        "generate_trading_signal"
      );

      const result = await generateTradingSignal();
      const newSignal = result.data;

      // Update state
      setSignal(newSignal);

      // Cache to localStorage for warm cache on next mount
      try {
        localStorage.setItem(SIGNAL_CACHE_KEY, JSON.stringify(newSignal));
      } catch (cacheErr) {
        console.warn("Failed to cache signal:", cacheErr);
      }
    } catch (err: any) {
      const errorMessage = err?.message || "Failed to generate trading signal";
      setError(errorMessage);
      console.error("Error generating trading signal:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    signal,
    loading,
    error,
    generateSignal,
  };
};
