import { useState, useCallback } from "react";
import { getFunctions, httpsCallable } from "firebase/functions";
import { app } from "@/firebase";

/**
 * Trade execution request parameters
 */
export interface ExecuteTradeRequest {
  symbol: string;
  side: "buy" | "sell";
  allocation_pct: number; // 0.0 to 1.0
  order_type?: "market" | "limit";
  current_price?: number; // Required for limit orders
  max_position_size?: number;
  metadata?: Record<string, any>;
}

/**
 * Trade execution response
 */
export interface ExecuteTradeResponse {
  success: boolean;
  client_order_id: string;
  alpaca_order_id: string;
  symbol: string;
  side: string;
  notional: string;
  order_type: string;
  limit_price?: string;
  status: string;
  message: string;
}

/**
 * Trade execution error
 */
export interface TradeExecutionError {
  code: string;
  message: string;
  details?: any;
}

interface UseTradeExecutorReturn {
  executeOrder: (request: ExecuteTradeRequest) => Promise<ExecuteTradeResponse>;
  loading: boolean;
  error: TradeExecutionError | null;
  lastExecution: ExecuteTradeResponse | null;
  clearError: () => void;
}

/**
 * Custom hook to execute trades via Firebase Functions.
 * 
 * Phase 4: The Trade Executor (OMS)
 * 
 * Provides a safe interface to execute trades with:
 * - Safety checks (trading gate)
 * - Audit logging (tradeHistory collection)
 * - Precision math (Decimal backend)
 * - Marketable limit orders for slippage protection
 */
export const useTradeExecutor = (): UseTradeExecutorReturn => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<TradeExecutionError | null>(null);
  const [lastExecution, setLastExecution] = useState<ExecuteTradeResponse | null>(null);

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  const executeOrder = useCallback(async (request: ExecuteTradeRequest): Promise<ExecuteTradeResponse> => {
    setLoading(true);
    setError(null);

    try {
      // Validate request locally first
      if (!request.symbol || typeof request.symbol !== "string") {
        throw new Error("Invalid symbol: must be a non-empty string");
      }

      if (!["buy", "sell"].includes(request.side)) {
        throw new Error("Invalid side: must be 'buy' or 'sell'");
      }

      if (typeof request.allocation_pct !== "number" || request.allocation_pct <= 0 || request.allocation_pct > 1) {
        throw new Error("Invalid allocation_pct: must be between 0 and 1");
      }

      const orderType = request.order_type || "limit";
      if (!["market", "limit"].includes(orderType)) {
        throw new Error("Invalid order_type: must be 'market' or 'limit'");
      }

      if (orderType === "limit" && !request.current_price) {
        throw new Error("current_price required for limit orders");
      }

      // Call Firebase Function
      const functions = getFunctions(app!);
      const executeTrade = httpsCallable<ExecuteTradeRequest, ExecuteTradeResponse>(
        functions,
        "execute_trade"
      );

      const result = await executeTrade(request);
      const response = result.data;

      // Store successful execution
      setLastExecution(response);

      // Log success
      console.log("Trade executed successfully:", response);

      return response;
    } catch (err: any) {
      const tradeError: TradeExecutionError = {
        code: err?.code || "UNKNOWN_ERROR",
        message: err?.message || "Failed to execute trade",
        details: err?.details || err
      };

      setError(tradeError);
      console.error("Trade execution failed:", tradeError);

      throw tradeError;
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    executeOrder,
    loading,
    error,
    lastExecution,
    clearError,
  };
};
