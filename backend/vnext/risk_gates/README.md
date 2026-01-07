# vNEXT Risk Gates (Governance-first)

Risk gates are **policy controls** that evaluate a decision context and return **data-only** recommendations to **allow**, **reduce**, or **block** *automated* actions.

## Core invariants

- **Gates never place trades**
  - Risk gates emit recommendations and auditable triggers only.
  - No broker/exchange SDKs, no order-routing, no side effects.

- **Gates never override humans**
  - A human decision is always authoritative.
  - When `decision_authority == "human"`, gate outputs are **advisory**:
    - the system may record triggers and recommendations for transparency
    - but it must not force a block/reduction against a human decision

These invariants align with `backend/vnext/GOVERNANCE.md` (OBSERVE-only by default; human authority always wins).

## Public interface

- **`RiskGate`**: Protocol for gate implementations (pure evaluation).
- **`GateTrigger`**: An auditable activation record (why a gate fired).
- **`GateAction`**: `ALLOW`, `REDUCE`, `BLOCK` (for automation).
- **`evaluate_risk_gates(context, gates)`**: Evaluate and conservatively combine gate outputs.

