# Strategy Promotion Framework (OBSERVE → SHADOW → PAPER → (FUTURE LIVE))

This document defines a **risk-governed promotion + demotion** framework for strategies progressing through:

- **OBSERVE**: compute signals only (no execution, no fills)
- **SHADOW**: simulate fills using live market data (no broker contact)
- **PAPER**: place orders in a paper environment (broker paper host / simulated order store)
- **(FUTURE) LIVE**: place orders in live markets (human-controlled, heavily gated)

The framework is designed to be:

- **Fail-closed by default** (unknown config ⇒ non-executing)
- **Auditable** (append-only, immutable promotion records)
- **Separable** from global execution gating (kill-switch, marketdata health, agent state machine)
- **Multi-tenant** (tenant + user scoped strategies)

---

## Non-negotiable safety invariants

- **Global execution kill-switch always wins**: `EXECUTION_HALTED=1` (or file) blocks broker-side actions regardless of stage.
- **Marketdata freshness gate is mandatory for execution**: if marketdata is stale, the execution agent must refuse (state machine `DEGRADED`).
- **Promotion changes must be auditable**: promotions/demotions produce immutable records with actor attribution and policy versioning.
- **Risk breaches demote immediately**: any critical risk event forces demotion to a safer stage (typically SHADOW or OBSERVE).

This promotion framework is **about strategy readiness**; it does not replace:
- kill-switch (`docs/KILL_SWITCH.md`)
- execution agent state machine (`docs/EXECUTION_AGENT_STATE_MACHINE.md`)
- circuit breakers (`backend/risk/circuit_breakers.py`)

---

## Definitions

### Stages (strategy lifecycle)

- **OBSERVE**
  - Strategy runs, emits signals + diagnostics only.
  - No orders created; no fills (real or simulated).
  - Output is evaluated against market outcomes to measure predictive quality.

- **SHADOW**
  - Strategy signals are converted into **synthetic orders** and **simulated fills** using live quotes.
  - No broker contact.
  - Trades are logged for P&L attribution and model debugging.
  - Existing implementation writes shadow trades to `shadowTradeHistory` and maintains shadow P&L.

- **PAPER**
  - Strategy signals may create “paper orders”.
  - Paper execution is permitted only when both:
    - runtime is configured for paper behavior (`TRADING_MODE=paper`), and
    - broker host is paper (e.g. Alpaca paper URL), and/or
    - the service uses the platform’s paper order path (`tenants/{tenant_id}/paper_orders/{id}`).

- **(FUTURE) LIVE**
  - Real broker orders.
  - Requires additional controls: explicit human approval, time-bounded enablement, strong identity, and confirmation token.

### Promotion vs execution gating

- **Promotion**: a governance decision recorded in Firestore that sets a strategy’s allowed lifecycle stage.
- **Execution gating**: runtime safety rails (kill-switch, agent mode, state machine readiness) that can override promotion.

Result: a strategy may be “promoted” to PAPER, but still effectively non-executing if:
- marketdata is stale, or
- kill-switch is enabled, or
- runtime is configured OBSERVE-only, or
- risk service denies a trade.

---

## 1) Promotion criteria (OBSERVE → SHADOW → PAPER → (FUTURE LIVE))

Promotion is evaluated using **three categories**:

- **Signal quality metrics**: “is the signal worth trading?”
- **Risk compliance**: “does it stay within limits?”
- **Operational stability**: “does it behave reliably?”

Each promotion requires:
- **minimum stability window** (time-based + trade-count based),
- **no critical violations** within window,
- **human approval checkpoint(s)** appropriate to the next stage.

### Policy structure

Promotion criteria are defined by a **tenant-scoped policy** (see Firestore layout below):
- default thresholds (global)
- per-strategy overrides (optional)
- versioned policy (`policy_version`) copied into each immutable promotion record

### A. OBSERVE → SHADOW (simulate fills; no broker)

**Goal**: show that the signal has predictive value and is safe to simulate at scale.

#### Signal quality metrics (minimums)
Evaluate on a rolling window aligned to market sessions:
- **Coverage**: strategy produces a non-HOLD action at least \(X\%\) of expected evaluation ticks (prevents “silent strategy”).
  - default: ≥ **90%** of scheduled evaluations produce a valid signal payload
- **Directional hit rate** (if applicable): fraction of signals where sign(signal) matches realized forward return sign at horizon \(H\).
  - default: ≥ **52%** over the window (small edge; tune per asset class)
- **Information coefficient (IC)**: Spearman correlation between signal score and forward returns.
  - default: mean IC ≥ **0.02**, and IC not negative for more than **60%** of days
- **Calibration / confidence sanity**: predicted confidence correlates with realized outcomes (monotonic buckets).
  - default: monotonicity pass in ≥ **4/5** confidence buckets

If the strategy is discrete (BUY/SELL/HOLD) rather than scored, replace IC with:
- **lift vs baseline**: improvement over random/hold baseline in hit rate or expected return.

#### Risk violation thresholds (must be zero critical)
Within the window:

- **No critical circuit breaker events**:
  - Daily loss limit breach (default breaker: −2% realized P&L vs starting equity) ⇒ fail promotion.
  - Any “switch to SHADOW_MODE” emergency action recorded by risk layer ⇒ fail promotion.
- **No execution-gating faults attributed to the strategy**:
  - repeated marketdata staleness attributable to the strategy’s required inputs (see data integrity section)
  - repeated schema/parse errors in strategy input events

#### Stability window (minimums)
- **Time**: ≥ **5 trading sessions** in OBSERVE
- **Evaluations**: ≥ **500** valid signal evaluations (or a tenant-tuned equivalent)

#### Human approval checkpoint
- **Required**: 1 approval by a designated **Strategy Reviewer** (or “auto-approve” for non-production tenants).
- **Record**: approval captured in an immutable promotion record (see below).

---

### B. SHADOW → PAPER (paper orders allowed; broker still non-live)

**Goal**: prove the strategy survives realistic execution mechanics (fills, latency, sizing, risk checks) without real money.

#### Signal quality metrics (minimums)
Measured from shadow fills / shadow P&L:
- **Profitability sanity**: positive expectancy net of modeled costs.
  - default: window return ≥ **0%**, and Sharpe (daily) ≥ **0.2** (tunable; avoid overfitting)
- **Drawdown containment**:
  - default: max drawdown ≤ **3%** in SHADOW window
- **Turnover bound** (prevents “hyperactive” strategies):
  - default: average daily turnover ≤ **1.5×** portfolio value (or asset-class tuned)

#### Risk violation thresholds (must be zero critical; limited warnings allowed)
- **Zero critical**:
  - daily loss circuit breaker activation (−2%) is a hard stop
  - any drawdown breaker configured as critical by tenant policy
  - concentration limit repeatedly exceeded (e.g., >20% position) more than a small allowance
- **Warning budget** (allowed but bounded):
  - VIX guard activations are allowed but must not coincide with repeated risk denials.

#### Operational stability (minimums)
- **Data quality**:
  - quote freshness: ≥ **99%** of fills have quote age ≤ configured max age
  - missing/NaN fields: ≤ **0.5%** of evaluation ticks
- **Error rate**:
  - strategy evaluation exceptions: ≤ **0.1%** of ticks
  - simulated fill failures: ≤ **0.1%** of attempted fills

#### Stability window (minimums)
- **Time**: ≥ **10 trading sessions** in SHADOW
- **Trades**: ≥ **50** simulated fills (or ≥ **1,000** signals if low-turnover)

#### Human approval checkpoints
- **Required**: 2-person approval (recommended):
  - **Risk Approver**: confirms breakers/limits, downside behavior, and adherence to policy.
  - **Ops Approver**: confirms stability, data quality, and observability.

---

### C. PAPER → (FUTURE) LIVE

**Goal**: demonstrate safe paper execution end-to-end and prove operational readiness for live controls.

> Note: this repo already enforces strong “do not execute live” guardrails; LIVE enablement should remain a controlled future step.

#### Signal quality metrics (minimums)
Measured from paper order outcomes (or paper broker fills if enabled):
- **Profitability & robustness**:
  - return ≥ **0%** over window (tunable)
  - max drawdown ≤ **2%**
  - no single-day loss worse than **−1%**
- **Slippage/latency realism**:
  - median decision-to-order latency within SLO (tenant-defined)
  - paper fills materially consistent with expected fills (no systematic pricing bugs)

#### Risk violation thresholds (hard gates)
- **Zero critical risk breaches** (daily loss limit, drawdown breaker, kill-switch events, unauthorized execution attempts).
- **No elevated denial rate** from risk service:
  - default: risk denial rate ≤ **2%** of attempted orders (above that indicates sizing/logic mismatch).

#### Operational stability (hard gates)
- **No repeated broker-side errors** (even in paper) suggesting integration instability:
  - default: order API error rate ≤ **0.5%**
- **No data integrity incidents** that impact trading decisions (see demotion triggers).

#### Stability window (minimums)
- **Time**: ≥ **20 trading sessions** in PAPER
- **Orders**: ≥ **100** paper orders

#### Human approval checkpoints (required)
- **3-step governance**:
  1. **Risk sign-off** (limits, stress behavior, rollback plan)
  2. **Ops sign-off** (observability, paging, runbook, kill-switch drill readiness)
  3. **Final Authorizer** (two-person rule) creates the LIVE enablement record
- **Execution confirmation** (future): require a time-bounded confirmation token (see `backend/common/execution_confirm.py`) for any transition that enables real broker placement.

---

## 2) Demotion triggers (automatic)

Demotion is an **automatic safety response**. It must:
- act quickly,
- be auditable,
- be conservative (demote to safer stage, not “retry live”).

### A. Risk breaches (hard demotion)

Demote **immediately** (usually to **SHADOW**, or to **OBSERVE** if data integrity is questionable) when any of the following occurs:

- **Daily loss limit breach** (default circuit breaker: −2% realized P&L vs starting equity)
- **Drawdown breaker** (tenant-defined; e.g., HWM drawdown > 5%)
- **Repeated concentration violations** indicating unsafe sizing/logic
- **Unauthorized execution attempt** detected by runtime guardrails (any “fatal execution path reached” event)

**Action**:
- set `execution_mode = "SHADOW_MODE"` (or `lifecycle_stage = "SHADOW"`), add `shadow_mode_reason`, and timestamp
- emit audit log + Firestore immutable demotion record
- notify operator + user (if applicable)

### B. Circuit breakers (policy-driven demotion)

- **Critical breaker** ⇒ demote to **SHADOW** and freeze promotions until manual review.
- **Warning breaker** (e.g., VIX guard) ⇒ do not demote by default, but increment a **warning counter**; demote if warnings exceed a threshold within a window.

### C. Data integrity issues (hard demotion)

Demote to **OBSERVE** (or freeze strategy) if:
- **Marketdata is stale** beyond the configured max age during decision/fill windows
- **Quote fields missing** (bid/ask/price) above threshold, causing unreliable fills
- **Time skew / clock drift** exceeds allowed skew (e.g., event timestamps in the future)
- **Schema drift** / parse errors occur repeatedly (poison inputs)
- **Replay/out-of-order** conditions cause non-deterministic behavior without idempotent safeguards

**Action**:
- set `lifecycle_stage = "OBSERVE"` and `freeze_reason = "data_integrity"`
- open an incident record (audit event) with evidence pointers (trace IDs, example payload hashes)

### D. Operational safety triggers (hard demotion)

Demote or freeze when:
- **Kill-switch enabled** (global): force strategies to non-executing posture
- **Execution agent not READY** (`DEGRADED`, `HALTED`, `ERROR`) while strategy is PAPER/LIVE
- **Broker/paper order path instability**: elevated 5xx, timeouts, repeated retries

---

## 3) Firestore configuration layout

This framework intentionally uses **tenant-scoped** configuration, with optional global defaults.

### A. Tenant promotion policy (versioned)

Path:
- `tenants/{tenant_id}/governance/promotion_policy`

Recommended fields:
- `policy_version`: string (e.g., `"2026-01-21.v1"`)
- `stability_windows`: map (min days, min signals, min trades per stage)
- `signal_quality_thresholds`: map (hit rate, IC, calibration, turnover)
- `risk_thresholds`: map (daily loss, drawdown, concentration)
- `data_integrity_thresholds`: map (stale rate, missing fields rate, max skew)
- `approval_matrix`: map (required roles per transition)
- `updated_at`: timestamp
- `updated_by`: string (uid/service)

### B. Strategy registry (per user, per tenant)

Existing pattern (used by circuit breakers):
- `tenants/{tenant_id}/users/{uid}/strategies/{strategy_id}`

Add/standardize fields (recommended):
- `status`: `"active"` | `"inactive"`
- `lifecycle_stage`: `"OBSERVE"` | `"SHADOW"` | `"PAPER"` | `"LIVE"`
- `execution_mode`: `"OBSERVE"` | `"SHADOW_MODE"` | `"PAPER"` (runtime mapping; keep `"SHADOW_MODE"` to match existing code)
- `policy_version`: string (the policy version currently applied)
- `last_stage_change_at`: timestamp
- `last_stage_change_record_id`: string (links to immutable promotion record)
- `freeze`: boolean (default false)
- `freeze_reason`: string|null
- `shadow_mode_reason`: string|null (used by circuit breaker demotion)
- `shadow_mode_activated_at`: timestamp|null
- `stage_overrides`: map|null (optional per-strategy thresholds/parameters)

### C. Promotion requests (mutable workflow state)

Path:
- `tenants/{tenant_id}/governance/promotion_requests/{request_id}`

Purpose:
- workflow object that can be updated while approvals are collected.

Fields (recommended):
- `strategy_id`, `uid`
- `from_stage`, `to_stage`
- `requested_at`, `requested_by`
- `status`: `"pending"` | `"approved"` | `"rejected"` | `"cancelled"`
- `approvals`: array/map of `{ role, approved_by, approved_at, comment }`
- `evidence_refs`: pointers to evaluation reports (doc ids / hashes)

Once a request is approved, it produces an **immutable promotion record** and the strategy doc is updated to reflect the new stage.

### D. Immutable promotion records (append-only)

Path:
- `tenants/{tenant_id}/governance/promotion_records/{record_id}`

This is the **source of truth** for “who changed what stage, when, and why”.

Recommended fields:
- `record_id`: string (ULID/UUID)
- `strategy_id`, `uid`
- `from_stage`, `to_stage`
- `decision`: `"promote"` | `"demote"` | `"freeze"` | `"unfreeze"`
- `policy_version`: string
- `requested_by`, `requested_at`
- `approved_by`: array of `{ role, uid, approved_at }`
- `effective_at`: timestamp
- `reason_code`: string (e.g., `"promotion_ready"`, `"daily_loss_limit_breached"`, `"data_integrity"`)
- `metrics_snapshot`:
  - `window_start`, `window_end`
  - key metrics (hit_rate, ic_mean, drawdown, etc.)
  - `metrics_hash`: string (hash of canonical metrics payload)
- `runtime_fingerprint`:
  - `git_sha`, `agent_name`, `service`, `env`
- `prev_record_hash`: string|null (optional per-strategy hash chain)
- `record_hash`: string (hash of canonical record payload)

Immutability requirements:
- backend writes MUST use Firestore `create()` (first writer wins)
- security rules MUST deny update/delete for this collection

### E. Audit events (append-only)

Path (recommended centralized log):
- `tenants/{tenant_id}/audit_events/{event_id}`

Event types to record:
- `strategy.promotion_requested`
- `strategy.promotion_approved`
- `strategy.promoted`
- `strategy.demoted`
- `risk.circuit_breaker_triggered` (can mirror existing per-user collection)
- `ops.data_integrity_event`

Fields:
- `event_type`, `severity`, `ts`
- `tenant_id`, `uid`, `strategy_id`
- `correlation_id` / `trace_id` (joinable with logs)
- `details` (small map; store large blobs elsewhere)

---

## 4) Audit logging requirements

### A. Structured logs (runtime)

All promotion/demotion actions MUST emit a structured log with:
- `event_type` (as above)
- `tenant_id`, `uid`, `strategy_id`
- `from_stage`, `to_stage`, `decision`
- `policy_version`
- `promotion_record_id`
- `correlation_id` / `trace_id`
- `git_sha` / version identifiers

### B. Firestore audit trail (persistent)

For every stage change:
- write **one immutable promotion record** (append-only)
- write **one audit event** (append-only)
- update the strategy doc’s `lifecycle_stage` / `execution_mode` and link `last_stage_change_record_id`

### C. Evidence retention

Promotion decisions must include references to evidence:
- evaluation reports (per-stage metrics summaries)
- example signal/trade samples (hashed)
- incident references (if demoted)

Evidence pointers should be stored in Firestore as **IDs + hashes**, not as large blobs.

---

## 5) Recommended “default action” mapping

When the system must choose a safe action:

- **Unknown config / missing policy** ⇒ **OBSERVE**
- **Risk critical event** ⇒ **SHADOW** (and/or freeze promotions)
- **Data integrity event** ⇒ **OBSERVE** + `freeze=true`
- **Kill-switch enabled** ⇒ deny broker-side actions regardless of stage; optionally set strategies to SHADOW for clarity

---

## 6) Notes on alignment with current repo behavior

- Global shadow toggle exists at `systemStatus/config.is_shadow_mode` and affects `execute_trade()` behavior (`docs/SHADOW_MODE.md`).
- Circuit breakers already demote by updating:
  - `tenants/{tenant_id}/users/{uid}/strategies/{strategy_id}.execution_mode = "SHADOW_MODE"`
  - plus `shadow_mode_reason` and `shadow_mode_activated_at`
- Paper orders are stored at:
  - `tenants/{tenant_id}/paper_orders/{id}` (see `backend/strategy_service/db.py`)

This framework formalizes those patterns and adds:
- versioned promotion policy
- explicit lifecycle stages
- immutable promotion records + centralized audit events

