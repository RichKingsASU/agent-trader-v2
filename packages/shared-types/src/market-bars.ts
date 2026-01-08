import type { EventEnvelope } from "./event-bus";

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

export type MarketBar1mEvent = EventEnvelope<MarketBar1mPayload> & {
  event_type: typeof MARKET_BARS_1M_EVENT_TYPE;
};

