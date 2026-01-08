export const MARKET_BARS_1M_EVENT_TYPE = "market.bars.1m" as const;
export const MARKET_BARS_1M_TOPIC_ID = "market-bars-1m" as const;

export type MarketBar1mPayload = {
  symbol: string;
  timeframe: "1m";
  ts: string; // ISO-8601 (UTC recommended)
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  source?: "alpaca" | "synthetic" | string;
};
/**
 * Payload-only contract.
 *
 * Envelope types live in adapter modules to keep a single canonical envelope definition.
 */

