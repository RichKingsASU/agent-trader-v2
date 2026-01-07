## Order Proposals (Signals → Auditable, Non-Executing Trade Intents)

Strategies in AgentTrader v2 are allowed to **evaluate** and produce trade *intents*, but must not execute broker orders unless explicitly authorized by a dedicated execution runtime.

The **Order Proposal** contract is the stable boundary between:
- **Decision**: strategies and signal generators
- **Execution**: a future execution agent/service that consumes proposals and (only when authorized) places orders

This separation makes behavior deterministic, auditable, and replay-friendly.

## Why proposals exist

- **Safety**: strategies can never directly place orders via this path.
- **Auditability**: every intent is logged and persisted as append-only NDJSON.
- **Replay-friendly**: proposals can be reprocessed by a future execution agent to validate decisions under the same inputs.
- **Standardization**: all strategies emit the same schema for trade intents.

## Schema overview

The shared contract lives in:
- `backend/trading/proposals/models.py`

Key fields:
- **`proposal_id`**: UUIDv4 identifier for idempotency/audit correlation
- **`created_at_utc`**: proposal creation timestamp (UTC)
- **`repo_id`**: repository identifier (e.g. `RichKingsASU/agent-trader-v2`)
- **`agent_name`**: workload identity emitting the proposal (e.g. `strategy-engine`)
- **`strategy_name` / `strategy_version`**: strategy identity (version optional)
- **`correlation_id`**: run correlation id for grouping (single strategy-loop run, etc.)
- **`symbol`**: underlying symbol (e.g. `SPY`)
- **`asset_type`**: `OPTION` (required for options), or `EQUITY` / `FUTURE`
- **`option`**: required when `asset_type=OPTION`
  - `expiration`: `YYYY-MM-DD`
  - `right`: `CALL` or `PUT`
  - `strike`: float
  - `contract_symbol`: optional provider-specific identifier
- **`side`**: `BUY` or `SELL`
- **`quantity`**: integer quantity (must be > 0)
- **`limit_price`**: optional price (for limit orders)
- **`time_in_force`**: `DAY` (default), `GTC`, or `IOC`
- **`rationale`**:
  - `short_reason`: short human-readable rationale
  - `indicators`: dict of redacted-safe indicators (no secrets)
- **`risk`**: optional risk hints (max loss / stop / take profit)
- **`constraints`**:
  - `valid_until_utc`: UTC expiry time (must not be in the past)
  - `requires_human_approval`: defaults to **true** (fail-safe)
- **`status`**: lifecycle status (`PROPOSED` default)

## Validation rules

Validation lives in:
- `backend/trading/proposals/validator.py`

Fail-safe rules (reject proposal on emit):
- missing required option fields when `asset_type=OPTION`
- `quantity <= 0`
- `valid_until_utc` is in the past
- `symbol` not allowed (if `SYMBOL_ALLOWLIST` is set)

Guard awareness:
- Proposals are allowed in any `AGENT_MODE`, but when not `AGENT_MODE=LIVE` the validator forces `requires_human_approval=true`.

## Emission and audit artifacts

Emission lives in:
- `backend/trading/proposals/emitter.py`

`emit_proposal()` performs:
- **Intent log** to stdout (Kubernetes/Cloud Run log collector friendly)
  - `event_type="intent"`
  - `intent_type="order_proposal"`
  - includes: proposal id, strategy, symbol, option summary, qty, limit, valid-until, requires-human-approval
- **Append-only NDJSON write** to:
  - `audit_artifacts/proposals/<YYYY-MM-DD>/proposals.ndjson`

Redaction:
- `rationale.indicators` is recursively redacted by key name (e.g. `api_key`, `token`, `password`, `secret`, etc.).

Read-only filesystem fallback:
- If the container filesystem cannot write `audit_artifacts/`, the emitter logs `event="audit_write_failed"` and prints a redacted proposal JSON line to stdout with `event_type="order_proposal_fallback"`.

## Example JSON

### OPTION CALL example

```json
{
  "proposal_id": "b9b0b3e7-4e5d-4cd5-8dc5-9f8b6e0d0b6a",
  "created_at_utc": "2026-01-07T12:00:00+00:00",
  "repo_id": "RichKingsASU/agent-trader-v2",
  "agent_name": "strategy-engine",
  "strategy_name": "gamma_scalper_0dte",
  "strategy_version": "1.0.0",
  "correlation_id": "run_20260107_120000",
  "symbol": "SPY",
  "asset_type": "OPTION",
  "option": {
    "expiration": "2026-01-14",
    "right": "CALL",
    "strike": 500.0,
    "contract_symbol": null
  },
  "side": "BUY",
  "quantity": 1,
  "limit_price": 1.23,
  "time_in_force": "DAY",
  "rationale": {
    "short_reason": "Bullish setup; buying call for defined risk.",
    "indicators": {
      "sma": 498.2,
      "flow_imbalance": 123456.0
    }
  },
  "risk": {
    "max_loss_usd": 123.0,
    "stop_loss": null,
    "take_profit": null
  },
  "constraints": {
    "valid_until_utc": "2026-01-07T12:05:00+00:00",
    "requires_human_approval": true
  },
  "status": "PROPOSED"
}
```

### OPTION PUT example

```json
{
  "proposal_id": "d0f9a8f0-2b1a-4f4c-8c74-20b8e02b0a0c",
  "created_at_utc": "2026-01-07T12:00:00+00:00",
  "repo_id": "RichKingsASU/agent-trader-v2",
  "agent_name": "strategy-engine",
  "strategy_name": "gamma_scalper_0dte",
  "strategy_version": "1.0.0",
  "correlation_id": "run_20260107_120000",
  "symbol": "SPY",
  "asset_type": "OPTION",
  "option": {
    "expiration": "2026-01-14",
    "right": "PUT",
    "strike": 480.0,
    "contract_symbol": null
  },
  "side": "BUY",
  "quantity": 1,
  "limit_price": 1.15,
  "time_in_force": "DAY",
  "rationale": {
    "short_reason": "Bearish hedge; buying put for defined risk.",
    "indicators": {
      "vix": 18.4
    }
  },
  "risk": {
    "max_loss_usd": 115.0,
    "stop_loss": null,
    "take_profit": null
  },
  "constraints": {
    "valid_until_utc": "2026-01-07T12:05:00+00:00",
    "requires_human_approval": true
  },
  "status": "PROPOSED"
}
```

## Future execution agent consumption

A future execution agent can safely consume proposals by:
- reading `proposals.ndjson` (or subscribing to a message bus carrying the same schema)
- re-validating proposals deterministically
- applying authorization checks (e.g., `AGENT_MODE=LIVE` + explicit approval / policy)
- converting proposals to execution intents for a broker adapter

Until that execution agent exists, proposals are **purely advisory** and **never place orders**.

