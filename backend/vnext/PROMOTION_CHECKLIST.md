# Promotion Readiness Checklist (vNext)

## Purpose
Define the **minimum promotion readiness criteria** for vNext components before enabling higher-risk modes (e.g., broader rollout, increased capital, more symbols, higher frequency, reduced human supervision).

This is **documentation only**: it specifies what must be true and what evidence must exist.

## Scope
Applies to any vNext change that can impact:
- trading decisions, order placement, position sizing, leverage, or risk limits
- safety/risk gates, circuit breakers, or kill switch behavior
- state persistence, audit logging, data lineage, or backtesting assumptions
- user/operator controls (human override), operational runbooks, or incident response

## Promotion metadata (required)
- **Change / release name**:
- **Components affected**:
- **Environment**: dev / staging / prod
- **Promotion type**: shadow → canary → partial → full (or equivalent)
- **Risk class**: Low / Medium / High
- **Owner (eng)**:
- **Owner (risk)**:
- **Date**:
- **Links**: PR(s), design doc(s), runbook(s), dashboards, tickets

## Checklist (must pass all required items)
For each item, attach **evidence** (link, screenshot, report, or file path) and record **who verified** and **when**.

### 1) Safety checks (required)
- [ ] **Known failure modes enumerated** (data outages, stale quotes, broker rejects, partial fills, rate limits, time sync, duplicated events).
  - Evidence:
  - Verified by / date:
- [ ] **Hard safety limits defined and enforced** (max order size, max notional, max position, max daily loss, max open orders).
  - Evidence:
  - Verified by / date:
- [ ] **Circuit breakers are implemented and validated** (including triggers, cooldowns, and safe-state behavior).
  - Evidence:
  - Verified by / date:
- [ ] **Kill switch works end-to-end** (halts new risk-taking actions; defines behavior for existing orders/positions).
  - Evidence:
  - Verified by / date:
- [ ] **Safe defaults on missing/invalid inputs** (e.g., conservative action, no-trade, or bounded outputs).
  - Evidence:
  - Verified by / date:
- [ ] **Operational monitoring is in place** (health, latency, error rates, risk metrics, order lifecycle, PnL/drawdown alarms).
  - Evidence:
  - Verified by / date:
- [ ] **Rollback procedure documented and rehearsed** (revert plan, config toggles, and expected recovery times).
  - Evidence:
  - Verified by / date:

### 2) Explainability present (required)
- [ ] **Decision trace is captured per action** (inputs → features → model/logic outputs → final decision).
  - Evidence:
  - Verified by / date:
- [ ] **Human-readable rationale is available** for key decisions (why trade/no-trade, why size, why timing).
  - Evidence:
  - Verified by / date:
- [ ] **Feature/data provenance is documented** (sources, timestamps, transformations, and staleness rules).
  - Evidence:
  - Verified by / date:
- [ ] **Versioning is explicit** (strategy/model version, config version, build fingerprint) and appears in logs/events.
  - Evidence:
  - Verified by / date:
- [ ] **Counterfactual / sensitivity notes recorded** for major changes (what would change the decision; known brittle regions).
  - Evidence:
  - Verified by / date:

### 3) Risk gates defined (required)
- [ ] **Promotion gates are written down** (what signals allow/stop promotion; thresholds; time windows; sample sizes).
  - Evidence:
  - Verified by / date:
- [ ] **Pre-trade risk checks defined** (symbol allowlist, liquidity/volatility constraints, market hours, news/halts, exposure caps).
  - Evidence:
  - Verified by / date:
- [ ] **Runtime risk gates are testable** (deterministic conditions, clear actions on breach, and no ambiguous states).
  - Evidence:
  - Verified by / date:
- [ ] **Post-trade / portfolio risk gates defined** (drawdown, concentration, correlation, exposure by sector/underlying, vega/gamma where relevant).
  - Evidence:
  - Verified by / date:
- [ ] **Fail-closed behavior defined** for gate subsystem failures (e.g., gate service unavailable, stale state, missing telemetry).
  - Evidence:
  - Verified by / date:

### 4) Human override tested (required)
- [ ] **Manual disable/enable controls exist** (documented command/API/UI path; access control and audit logging).
  - Evidence:
  - Verified by / date:
- [ ] **Emergency stop validated** under realistic conditions (active orders, partial fills, delayed acknowledgements).
  - Evidence:
  - Verified by / date:
- [ ] **Operator runbook exists** for overrides (who can act, escalation path, decision tree, comms template).
  - Evidence:
  - Verified by / date:
- [ ] **Override actions are observable** (events/logs/metrics show the change immediately and unambiguously).
  - Evidence:
  - Verified by / date:
- [ ] **Restore-from-override procedure validated** (how to safely resume; required checks before re-enable).
  - Evidence:
  - Verified by / date:

### 5) Audit artifacts available (required)
- [ ] **Audit log completeness verified** (who/what/when/why for: config changes, overrides, gate decisions, trades, failures).
  - Evidence:
  - Verified by / date:
- [ ] **Reproducibility package available** (config snapshot, code revision, dependencies/build info, environment identifiers).
  - Evidence:
  - Verified by / date:
- [ ] **Data retention and access policy documented** (retention periods, redaction rules, access controls, incident access).
  - Evidence:
  - Verified by / date:
- [ ] **Backtest/sim artifacts linked** (datasets, assumptions, evaluation metrics, known limitations, comparison vs prior baseline).
  - Evidence:
  - Verified by / date:
- [ ] **Operational evidence preserved** for promotion window (dashboards, alerts, incident tickets, change tickets).
  - Evidence:
  - Verified by / date:

## Promotion decision (required)
- **Decision**: Approved / Approved with conditions / Rejected
- **Conditions (if any)**:
- **Go-live window**:
- **Monitoring plan for first 24–72h**:
- **Rollback trigger thresholds**:

## Sign-off (required)
- **Engineering owner**: ____________________  Date: __________
- **Risk owner**: __________________________  Date: __________
- **Operations / on-call**: _________________  Date: __________

