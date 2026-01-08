import type { EventEnvelope } from "./envelope";
import type { MarketBar1mPayload } from "./market-bars";
import { MARKET_BARS_1M_EVENT_TYPE } from "./market-bars";

/**
 * Adapter type: payload + canonical envelope.
 *
 * Note: this is type-only; no runtime behavior.
 */
export type MarketBar1mEvent = EventEnvelope<MarketBar1mPayload> & {
  event_type: typeof MARKET_BARS_1M_EVENT_TYPE;
};

