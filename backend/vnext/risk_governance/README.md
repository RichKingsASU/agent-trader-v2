# vNEXT Risk Governance (Global Kill Switch)

This folder defines **interfaces only** for human authority overrides.

## Principles

- **Manual only**: governance actions are performed by authorized humans (or tightly-controlled ops tooling acting on explicit human intent).
- **Logged always**: every governance action must emit an immutable `GovernanceAuditRecord`.
- **Overrides automation**: governance decisions (e.g., kill switch) take precedence over all automated strategy/execution decisions.

## Scope

- No implementations or business logic live here.
- `interfaces.py` provides type contracts for checking whether trading is allowed and reading the current governance state.

