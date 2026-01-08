import type { IsoDateTimeString, PubSubEvent } from "./pubsub";

/**
 * Market data payloads + Pub/Sub event schemas (v1).
 *
 * These are additive exports: they do not change runtime behavior and do not
 * replace any existing internal types elsewhere in the repo.
 *
 * Versioning guidance:
 * - Add optional fields freely (e.g. new venue codes, additional metrics).
 * - If you must add a required field or change meanings/units, publish a new
 *   payload type and new event schema (e.g. MarketBarEventV2 with schemaVersion: 2).
 */

export type MarketDataProvider =
  | "alpaca"
  | "polygon"
  | "iex"
  | "tradier"
  | "interactive_brokers"
  | "unknown"
  | (string & {});

export type MarketVenue =
  | "NYSE"
  | "NASDAQ"
  | "ARCA"
  | "BATS"
  | "IEX"
  | "OTC"
  | "UNKNOWN"
  | (string & {});

/**
 * Canonical instrument identifier.
 *
 * Prefer `symbol` (e.g. "AAPL") for equities; extend with `assetClass` if needed.
 * Additive changes only; do not repurpose fields.
 */
export type InstrumentRef = {
  symbol: string;
  assetClass?: "equity" | "option" | "future" | "fx" | "crypto" | "unknown";
  /**
   * Optional provider-specific identifier (e.g. FIGI, composite code, internal id).
   */
  instrumentId?: string;
};

/**
 * OHLCV bar payload (v1).
 *
 * Time fields:
 * - `startAt`/`endAt` represent the bar window in ISO string form.
 */
export type MarketBarPayloadV1 = {
  instrument: InstrumentRef;
  timeframe:
    | "1s"
    | "5s"
    | "10s"
    | "15s"
    | "30s"
    | "1m"
    | "2m"
    | "5m"
    | "10m"
    | "15m"
    | "30m"
    | "1h"
    | "4h"
    | "1d"
    | "1w"
    | "1mo"
    | (string & {});
  startAt: IsoDateTimeString;
  endAt: IsoDateTimeString;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  vwap?: number;
  tradeCount?: number;
  provider?: MarketDataProvider;
  venue?: MarketVenue;
  /**
   * Preserve provider extras without breaking consumers.
   */
  meta?: Record<string, unknown>;
};

/**
 * Quote/tick payload (v1).
 */
export type MarketTickPayloadV1 = {
  instrument: InstrumentRef;
  observedAt: IsoDateTimeString;
  bid?: number;
  bidSize?: number;
  ask?: number;
  askSize?: number;
  /**
   * Last traded price/size if present in the feed.
   */
  last?: number;
  lastSize?: number;
  provider?: MarketDataProvider;
  venue?: MarketVenue;
  meta?: Record<string, unknown>;
};

/**
 * Trade payload (v1).
 */
export type MarketTradePayloadV1 = {
  instrument: InstrumentRef;
  tradedAt: IsoDateTimeString;
  price: number;
  size?: number;
  /**
   * Side is often unknown at the venue level; keep optional.
   */
  side?: "buy" | "sell" | "unknown";
  provider?: MarketDataProvider;
  venue?: MarketVenue;
  /**
   * Provider trade id, if available.
   */
  tradeId?: string;
  meta?: Record<string, unknown>;
};

/** Pub/Sub event schemas (v1). */
export type MarketBarEventV1 = PubSubEvent<"market.bar", 1, MarketBarPayloadV1>;
export type MarketTickEventV1 = PubSubEvent<"market.tick", 1, MarketTickPayloadV1>;
export type MarketTradeEventV1 = PubSubEvent<
  "market.trade",
  1,
  MarketTradePayloadV1
>;

export type MarketDataEventV1 =
  | MarketBarEventV1
  | MarketTickEventV1
  | MarketTradeEventV1;

