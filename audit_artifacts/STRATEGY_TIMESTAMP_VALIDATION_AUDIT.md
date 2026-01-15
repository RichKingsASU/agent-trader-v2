## Strategy Timestamp Validation Audit

Date: 2026-01-14  
Role: Freshness Coverage Auditor  
Scope: Strategies in this repo that consume **event timestamps** (market events, bars, or news items) and can place/emit actions based on them.

### Validation definition (what counts as “validates event timestamps”)

- **Parse/shape**: timestamp is present (where required) and parseable into a UTC time
- **Freshness**: event age must be \(\le\) configured max age
- **Future skew**: event timestamp must not be too far ahead of “now” (guards clock skew / bad upstream data)

Defaults (override via env):
- `STRATEGY_EVENT_MAX_AGE_SECONDS=30`
- `STRATEGY_EVENT_MAX_FUTURE_SKEW_SECONDS=5`

### Results (PASS/FAIL)

| Strategy | Location | Timestamp source | Validation location | Checks enforced | Result |
|---|---|---|---|---|---|
| `naive_flow_trend` | `backend/strategy_engine/strategies/naive_flow_trend.py` | DB bars (`public.market_data_1m.ts`) | `backend/strategy_engine/driver.py` | Freshness (stale-after) + future-skew | **PASS** |
| `llm_sentiment_alpha` | `backend/strategy_engine/strategies/llm_sentiment_alpha.py` | Alpaca news (`NewsItem.timestamp`) | `backend/strategy_engine/sentiment_strategy_driver.py` | Freshness (within lookback window) + future-skew | **PASS** |
| `hello_strategy` | `backend/strategy_runner/examples/hello_strategy/strategy.py` | `MarketEvent.ts` (ISO8601 string) | `backend/strategy_runner/guest/guest_runner.py` | Parse + freshness + future-skew | **PASS** |
| `congressional_alpha` | `backend/strategy_runner/examples/congressional_alpha/strategy.py` | `MarketEvent.ts` (ISO8601 string) | `backend/strategy_runner/guest/guest_runner.py` | Parse + freshness + future-skew | **PASS** |
| `gamma_scalper_0dte` | `backend/strategy_runner/examples/gamma_scalper_0dte/strategy.py` | `MarketEvent.ts` (ISO8601 string) | `backend/strategy_runner/guest/guest_runner.py` | Parse + freshness + future-skew | **PASS** |
| `options_bot` | `backend/strategies/options_bot.py` | NATS `MarketEventV1.ts` (pydantic datetime) | `backend/strategies/options_bot.py` | Freshness + future-skew | **PASS** |
| `delta_momentum_bot` | `agenttrader/backend/strategies/delta_momentum_bot.py` | NATS JSON payload (`ts` / `timestamp` / `event_ts` / `created_at` / `time`) | `agenttrader/backend/strategies/delta_momentum_bot.py` | Required timestamp + parse + freshness + future-skew | **PASS** |

