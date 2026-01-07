# vNEXT — Cross-Cutting Governance Rules

This document defines **global, cross-cutting governance rules** for all vNEXT modules. These rules apply to **every** package, service, job, worker, agent, CLI, notebook, and test that is part of vNEXT.

## Scope & definitions

- **vNEXT module**: Any code under `backend/vnext/` (and any code explicitly marked as vNEXT elsewhere).
- **Observation**: Reading data, computing signals, generating summaries, proposals, alerts, or recommendations.
- **Execution**: Any action that can place/cancel/modify orders, move funds, alter production state, or trigger side effects in external systems.
- **Live dependency**: Any runtime reliance on a real external system (broker/exchange, live market data stream, production database, production queues, third‑party APIs) during normal unit/integration test execution or local development runs.

---

## Rule 1 — OBSERVE-only by default

vNEXT is **observation-first**. The default behavior of all vNEXT components is to **observe and propose**, not to act.

- **Allowed**
  - Compute indicators, risk metrics, or forecasts.
  - Generate trade **proposals** (e.g., suggested orders) as data structures or documents.
  - Produce logs, dashboards, alerts, and audit artifacts.
  - Run simulations/backtests using recorded or synthetic data.
- **Forbidden by default**
  - Placing/cancelling/modifying orders.
  - Writing to production state stores as a side effect of analysis.
  - Triggering external workflows that could cause execution (directly or indirectly).

If an exception is ever required, it must be implemented in a **separate, non-vNEXT execution layer** and guarded by explicit, reviewable controls (see Rule 4).

---

## Rule 2 — No execution coupling

vNEXT must not be structurally coupled to execution. This ensures analysis modules remain safe, testable, and portable.

- **Must not**
  - Import execution-engine packages, broker SDKs, or order-routing libraries.
  - Call order endpoints, execution RPCs, or “trade now” triggers.
  - Define types that require execution dependencies to import/instantiate.
  - Encode execution behavior in callbacks/hooks (“when signal fires, place order”).
- **Must**
  - Represent outputs as **intent/proposal objects** (pure data), e.g. `TradeProposal`, `PositionAdjustment`, `RiskAlert`.
  - Use explicit boundary interfaces for any downstream consumer (e.g. `ProposalSink`, `AlertSink`), implemented outside vNEXT.

**Design principle**: vNEXT emits *information* and *recommended intents*; something else (outside vNEXT) decides whether to execute.

---

## Rule 3 — No live dependencies

vNEXT must run deterministically in local/dev/test environments without requiring live external systems.

- **Must not**
  - Reach out to real broker/exchange endpoints in unit/integration tests.
  - Depend on live market data feeds for correctness.
  - Read/write production databases/queues from tests or default local runs.
  - Require network availability to run core logic.
- **Must**
  - Use adapter interfaces for all I/O (market data, storage, messaging, HTTP).
  - Provide in-repo **mocks/fakes/fixtures** as the default test path.
  - Make “live mode” an explicit opt-in controlled by configuration and environment guards (and still never coupled to execution per Rule 2).

**Testing expectation**: Core logic is validated against recorded datasets or synthetic fixtures with stable snapshots.

---

## Rule 4 — Human authority always wins

Humans retain final authority over execution and safety outcomes. vNEXT must be built to support overrides and safe shutdown.

- **Must**
  - Treat human decisions as the source of truth, even when they conflict with model outputs.
  - Provide clear explainability artifacts: inputs, assumptions, versions, and rationale for every proposal.
  - Emit auditable logs for significant decisions and proposal generation (who/what/when/why).
  - Respect emergency controls (kill-switches / disable flags) provided by the platform.
- **Must not**
  - Auto-escalate proposals into execution without an explicit, human-controlled workflow outside vNEXT.
  - Hide uncertainty; if confidence is low or inputs are stale, the system must surface that.

**Operational invariant**: When a human says “stop”, vNEXT must not be able to force “go”.

---

## Rule 5 — Every module must be mockable

Every vNEXT module must be easy to isolate and test. Mockability is mandatory, not optional.

- **Must**
  - Separate pure computation from I/O via clean interfaces.
  - Use dependency injection (constructor parameters, function args, or explicit providers) for time, randomness, data sources, and sinks.
  - Prefer pure functions and immutable inputs/outputs for core logic.
  - Provide typed protocols/interfaces for external interactions (e.g., `MarketDataClient`, `Clock`, `Storage`, `Notifier`).
- **Must not**
  - Hide dependencies in global singletons, module-level side effects, or implicit environment reads.
  - Require network calls as part of object construction.
  - Entangle business logic with framework lifecycle code.

**Review rule of thumb**: If a unit test needs monkeypatching of globals to run, the module is likely violating this rule.

---

## Implementation guidelines (how to comply)

- **Boundary-first design**
  - Put pure domain logic in small functions/classes.
  - Put adapters at the edges; adapters can be swapped with fakes.
- **Configuration guards**
  - Default config is non-live, non-executing, and safe.
  - Live connections (data only) must require explicit opt-in and strong environment checks.
- **Data outputs over imperative actions**
  - Produce proposals/alerts as data records.
  - Persist artifacts for review (JSON/CSV/markdown) rather than triggering actions.

---

## Compliance checklist (PR reviewer quick scan)

- **OBSERVE-only**: No code path places/cancels/modifies orders.
- **No execution coupling**: No imports/calls into execution engine or broker SDKs.
- **No live deps**: Tests run offline with mocks/fixtures; no network required.
- **Human authority**: Clear override paths, auditable rationale, respects kill-switch patterns.
- **Mockable**: Dependencies injected; core logic testable without patching globals.

---

## Non-goals

- This document does not define strategy quality, profitability, or model selection criteria.
- This document does not replace existing platform security policies; it complements them for vNEXT-specific safety boundaries.

