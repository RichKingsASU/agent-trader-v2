/**
 * Trade signal payload (execution-oriented).
 *
 * Mirrors `backend/alpaca_signal_trader.py` (`TradeSignal`) at the JSON level.
 * Payload-only: wrap with `EventEnvelope<T>` at the transport boundary.
 */
export type TradeSignalPayload = {
  action: string; // "buy" | "sell" | "flat" (kept as string for forward-compat)
  symbol: string;
  notional_usd: number;
  reason: string;
  raw_model_output?: Record<string, unknown> | null;
};

