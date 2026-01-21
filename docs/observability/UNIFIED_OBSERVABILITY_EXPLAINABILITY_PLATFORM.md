# Unified Observability & Explainability Platform — AgentTrader v2

This document defines a unified **observability + explainability** platform for AgentTrader v2.
It builds on the repo’s existing conventions:

- Structured JSON logs with stable keys (`docs/STRUCTURED_LOGGING_STANDARD.md`, `docs/observability/logging.md`)
- Canonical event envelope (`docs/event_contract_v1.md`) with required `trace_id`
- Correlation + execution scoping primitives (`backend/observability/correlation.py`, `backend/observability/execution_id.py`)

**Safety constraint (non-negotiable)**: observers are **read-only** and must have **no feedback path** into execution.

---

## Architecture (unified, explainability-first)

### Control planes

- **Execution plane (mutable, safety-critical)**
  - Strategy engine, risk service, execution engine/agent, market ingest.
  - Produces **facts**: structured logs + canonical domain events.
  - Must not depend on observer availability.

- **Observer plane (immutable, explainability + ops)**
  - Consumes facts (Pub/Sub subscriptions, Cloud Logging sinks, metrics scraping).
  - Produces **derived artifacts**: explanation timeline, trade narrative, attribution summaries.
  - Must be “fail-open” w.r.t. execution: observer outages cannot block trading.

### Data flow (high-level)

1) **Emit**: Every service emits JSON logs and canonical `EventEnvelope` messages.
2) **Collect**:
   - Cloud Logging captures logs.
   - Pub/Sub transports domain events.
   - Cloud Monitoring/Prometheus captures metrics.
3) **Persist (append-only)** into an **Explainability Store**:
   - **Hot**: Cloud Logging (fast incident triage)
   - **Warm**: BigQuery (analytics, timelines, joins)
   - **Cold/Audit**: GCS (long retention export, immutable snapshots)
4) **Serve** via read-only APIs/UI:
   - Timeline UI (strategy decisions + evidence)
   - Trade narrative reconstruction (end-to-end story per execution)

### Reference implementation mapping (repo-aligned)

- **Logs**: `backend/observability/logger.py`, `backend/observability/ops_json_logger.py`
  - Always includes `correlation_id`, `execution_id`, and mirrors `trace_id` to `correlation_id` today.
- **Events**: `docs/event_contract_v1.md` (`EventEnvelope` with required `trace_id`)
  - Domain events must carry enough IDs to join across stages.

---

## Definitions (three-layer observability)

### 1) Signal-level observability (Why did the strategy “think” this?)

Captures the full decision context and evidence chain that produced a trade intention.

**Scope**
- Market observations used (prices, flows, news, derived candles).
- Feature computation and model inference outputs (scores, confidences, thresholds).
- Decision gating (cooldowns, regime filters, liquidity checks, “do nothing” reasons).

**Required guarantees**
- Evidence is reconstructable without re-running the strategy code.
- Feature/model outputs are logged/stored in a redacted, bounded form (no secrets).
- “No trade” is observable (explicit `noop` outcome with reason codes).

### 2) Execution-level observability (What happened in the market/broker?)

Captures the order lifecycle and broker/venue interactions.

**Scope**
- Proposal → risk check → order submission → acknowledgements → fills → cancels/replace.
- Latencies at each stage, retries, idempotency outcomes, broker error surfaces.
- Slippage, partial fills, price improvements, rejection reasons.

**Required guarantees**
- Every order has a stable ID chain (proposal → order → fills).
- Every retry is linked to the same `execution_id` and has explicit idempotency semantics.

### 3) Risk-level observability (Was it allowed, and did it remain safe?)

Captures risk checks before and after execution, and continuous safety state.

**Scope**
- Pre-trade risk evaluation results, limits consulted, reservations made.
- Portfolio risk snapshots (exposure, drawdown, concentration, leverage, VaR-ish proxies if used).
- Circuit breaker trips, kill switch state, degraded modes.

**Required guarantees**
- Risk is explainable in terms of limits + computed metrics with units.
- Trips and overrides are audit-grade and immutable.

---

## Required structured log events (minimum viable set)

Logs are for **operator triage** and log-based metrics. Domain events (next section) are for **reconstruction**.
Log schema must follow the stable keys in `docs/STRUCTURED_LOGGING_STANDARD.md`.

### Common required fields (all events below)

- `event_type` (stable discriminator)
- `outcome` ∈ `success|failure|noop|duplicate|degraded|started`
- `correlation_id` (request/message correlation)
- `execution_id` (execution attempt scope; may be null when not applicable)
- `latency_ms` or `duration_ms` (one of them, integer milliseconds, when timing is relevant)

### Signal-level log events

- `signal.observe` (INFO): “new observation accepted for strategy”
  - Required extras: `symbol`, `source`, `observed_at`
- `signal.features` (INFO): “features computed”
  - Required extras: `feature_set_id`, `feature_digest`, `feature_count`
- `signal.inference` (INFO): “model inference complete”
  - Required extras: `model_id`, `model_version`, `score`, `threshold`, `decision`
- `signal.gate` (INFO/WARNING): “gating decision”
  - Required extras: `gate_name`, `gate_result`, `reason_code`

### Execution-level log events

- `execution.proposal` (INFO): “order proposal created”
  - Required extras: `proposal_id`, `symbol`, `side`, `qty|notional`, `order_type`
- `execution.submit` (INFO): “submitted to broker/venue”
  - Required extras: `order_id`, `broker`, `client_order_id`
- `execution.fill` (INFO): “fill observed”
  - Required extras: `order_id`, `fill_id`, `filled_qty`, `fill_price`
- `execution.reject` (WARNING/ERROR): “broker rejected”
  - Required extras: `order_id|client_order_id`, `reject_code`, `reject_message`

### Risk-level log events

- `risk.check` (INFO/WARNING): “pre-trade risk check evaluated”
  - Required extras: `risk_eval_id`, `decision` (`allow|deny|defer`), `reason_code`
- `risk.reserve` (INFO): “capital reserved”
  - Required extras: `reservation_id`, `amount_usd`
- `risk.breaker` (WARNING/ERROR): “circuit breaker state change”
  - Required extras: `breaker_name`, `state` (`armed|tripped|cleared`), `reason_code`

---

## Correlation IDs (join strategy: logs ⇄ events ⇄ timelines)

AgentTrader should treat IDs as **join keys**. Every record should carry the minimum set needed to join across layers.

### Canonical IDs (must exist when applicable)

- **`trace_id`** (events): end-to-end flow correlation (required by `EventEnvelope`)
- **`correlation_id`** (logs): request/message correlation (today mirrors `trace_id`; keep aligned)
- **`execution_id`**: execution attempt scope (proposal/risk/submit/fills share it)
- **`event_id`**: unique event identifier for idempotency and de-duplication (recommended everywhere)

### Domain IDs (recommended)

- **Strategy**: `strategy_id`, `strategy_version`, `strategy_run_id`
- **Decision**: `decision_id` (one per “should we trade?” evaluation)
- **Proposal**: `proposal_id`
- **Orders/Fills**: `client_order_id`, `order_id`, `fill_id`
- **Risk**: `risk_eval_id`, `reservation_id`, `limit_set_id`
- **Portfolio**: `portfolio_id`, `account_id`, `position_id`

### Propagation rules (hard requirements)

- New decision evaluation generates/uses one `trace_id`; it is reused for:
  - signal evidence → decision → risk check → execution → fills → post-trade attribution
- Each *execution attempt* binds one `execution_id`; retries keep the same `execution_id` and add:
  - `attempt` (integer) and `idempotency_key` (string)
- Every service must log and emit events with the active `correlation_id/trace_id` already supported by:
  - `backend/observability/correlation.py`
  - `backend/observability/logger.py` (mirrors `trace_id` to `correlation_id`)

---

## Retention policy (hot/warm/cold, by data class)

Retention must balance audit needs, cost, and privacy. Default policy below is intended for production.

### Tiers

- **Hot (ops)**: Cloud Logging, fast queries, low friction
- **Warm (analytics)**: BigQuery, joinable event history
- **Cold (audit)**: GCS, immutable export snapshots

### Recommended defaults

| Data class | Examples | Hot (Cloud Logging) | Warm (BigQuery) | Cold (GCS) |
|---|---|---:|---:|---:|
| Debug | verbose traces, feature dumps | 7 days | 30 days | 0 |
| Ops | health, errors, retries | 30 days | 180 days | 0–365 days (optional) |
| Explainability | decision steps, evidence pointers | 30 days | 365 days | 2–7 years |
| Trade audit | orders, fills, cancels, risk decisions | 90 days | 2–7 years | 7 years |

**Rules**
- Do not store secrets; apply redaction (see `backend/observability/logger.py` redaction helpers).
- If an event is “audit-grade”, store it as immutable (append-only) and protect it with retention locks where supported.

---

## Strategy explanation timeline (design)

### Goal

Provide a time-ordered, joinable, immutable sequence that answers:
“**What did the strategy observe, what did it believe, what constraints applied, and what did it decide?**”

### Timeline model (append-only)

Store a derived `explain.step` record for each decision stage. A step is **derived** from facts (events/logs), not authored by a UI.

Minimum fields:
- `ts` (step time)
- `trace_id`, `execution_id` (join keys)
- `strategy_id`, `strategy_version`, `strategy_run_id`
- `step` (enum): `observe|features|inference|gate|proposal|risk|submit|fill|post_trade`
- `summary` (short human text, safe + bounded)
- `reason_codes` (array of strings)
- `evidence` (array of pointers): references to immutable artifacts (event_id(s), log filters, BigQuery row ids, or GCS object refs)

### Evidence pointers (no recompute requirement)

To avoid re-running models/strategies for explanation:
- Store **feature digests** and **model outputs** at decision time.
- Store **market observation references** (symbol + provider + sequence/time + canonical candle id).
- Store **risk inputs** (equity, exposure snapshot id, limit set version).

---

## Trade narrative reconstruction (design)

### Goal

Rebuild a coherent “story” per trade/execution:

> “At \(t0\) strategy X observed Y, inferred Z, passed gates A/B, proposed order P, risk allowed it under limits L, submitted order O, got fills F1..Fn, realized slippage S, and updated PnL attribution.”

### Reconstruction algorithm (deterministic)

1) Select a root key:
   - Prefer `execution_id`; fallback to `order_id` or `trace_id`.
2) Fetch all domain events + key logs matching the root key.
3) Normalize time ordering:
   - Use `EventEnvelope.ts` for producer time; add ingestion time as a secondary order key.
4) Build the narrative segments:
   - **Signal context**: `signal.*` + `decision.*`
   - **Risk context**: `risk.*` including allow/deny with reason codes + snapshots
   - **Execution**: order lifecycle + fills; compute derived metrics:
     - submission latency, time-to-first-fill, fill completion time
     - slippage vs reference price at proposal time
5) Emit a derived `narrative.v1` artifact into the Explainability Store (read-only served).

### Output shape (for UI/API)

- `title`, `status`, `timestamps` (start/end)
- `actors` (strategy, risk service, execution agent, broker)
- `segments[]` (each with `summary`, `facts[]`, `links[]`)
- `metrics` (slippage, latencies, realized pnl, risk utilization deltas)

---

## Event taxonomy (domain events for reconstruction)

These are canonical **domain events** (transported in `EventEnvelope`) used for joins and reconstruction.
They are distinct from logs (which are for ops triage).

### Naming conventions

- Use dot-delimited namespaces: `signal.*`, `decision.*`, `risk.*`, `execution.*`, `portfolio.*`, `system.*`
- Each event must include the join keys relevant to its stage (`trace_id` always; `execution_id` when relevant).

### Signal-level events

- `signal.observed` (market/news/flow observation accepted)
- `signal.features_computed` (feature set id + digest)
- `signal.model_inferred` (model id/version + score + threshold + decision)
- `signal.gate_evaluated` (gate name + pass/fail + reason_codes)

### Decision events

- `decision.evaluated` (the “should we trade?” decision point)
- `decision.noop` (explicit “do nothing” with reason_codes)
- `decision.proposal_created` (proposal id + intent summary)

### Risk events

- `risk.evaluated` (allow/deny/defer + limit set + reasons)
- `risk.capital_reserved` (reservation id + amount)
- `risk.circuit_breaker_changed` (armed/tripped/cleared + reasons)
- `risk.snapshot` (portfolio risk metrics snapshot pointer)

### Execution events

- `execution.order_submitted` (client_order_id/order_id + broker)
- `execution.order_acknowledged`
- `execution.order_rejected`
- `execution.order_filled` (fill id + qty/price)
- `execution.order_cancelled` / `execution.order_replaced`
- `execution.settlement_observed` (if applicable)

### Portfolio/PnL events

- `portfolio.position_changed` (position id + delta)
- `portfolio.pnl_attributed` (realized/unrealized + attribution breakdown pointer)

### System/safety events (cross-cutting)

- `system.heartbeat`
- `system.degraded_mode_changed`
- `system.kill_switch_changed`
- `system.idempotency_duplicate_dropped`

---

## Read-only observers (no feedback into execution paths)

### Hard boundaries (must be enforced by IAM + network)

- Observer workloads:
  - **May read**: Cloud Logging, BigQuery datasets, Firestore read replicas/exports, Pub/Sub subscriptions.
  - **May not write**: execution topics, trading APIs, strategy/risk/execution control endpoints.

### Required controls

- **IAM**
  - Use dedicated observer service accounts.
  - Grant only read roles (Logging Viewer, BigQuery Data Viewer, Pub/Sub Subscriber).
  - Explicitly deny publisher/admin roles on any execution topics.
- **Network**
  - Separate namespaces and default-deny egress where possible.
  - No network route to broker credentials, execution services, or internal control endpoints.
- **Topic hygiene**
  - Observers subscribe to topics; they never publish to the same bus used by execution.
  - If observers must emit artifacts, they write only to the Explainability Store (BigQuery/GCS) and only through a controlled ingestion path.
- **Operational posture**
  - Observer plane is “observe-only” consistent with `docs/runbooks/k8s-rollout-procedure-observe-only.md`.

---

## Summary (what you get)

- **Signal-level observability**: evidence-backed decision context (features + model outputs + gate decisions).
- **Execution-level observability**: order lifecycle, latency, and broker outcomes tied to decisions.
- **Risk-level observability**: allow/deny explanations and ongoing safety state.
- **Explainability artifacts**:
  - Strategy explanation timeline (stepwise, immutable, joinable)
  - Trade narrative reconstruction (deterministic story per `execution_id`)
- **Safety**: observers are strictly read-only with no feedback path into execution.

