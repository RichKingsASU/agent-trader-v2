# AgentTrader v2 — Institutional Hardening Execution Board

## Summary
- **Current phase (Tier)**: Tier 1
- **Overall % complete (manual)**: 0%
- **Current sprint goals (manual)**:
  - Establish Tier 1 governance primitives (identity/intent logging, AGENT_MODE guard, agent responsibilities doc)
  - Stand up deterministic in-repo tracking + weekly cadence

## Task Board

<!--
Deterministic editing notes:
- The table between TASKS_START/TASKS_END is machine-edited by `scripts/update_execution_board.py`.
- Keep the column order unchanged.
- Dependencies should reference other IDs (comma-separated), or `-`.
-->

<!-- TASKS_START -->
| ID | Tier | Task | Owner | Status | Dependencies | Acceptance Criteria | Evidence | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AT-001 | 1 | Agent identity + intent logging | TBD | TODO | - | Identity and intent are recorded for every agent-run entrypoint; logging format documented; includes correlation/run id. | - | Planning-only: do not enable trading. |
| AT-002 | 1 | AGENT_MODE guard | TBD | TODO | - | AGENT_MODE (or equivalent) prevents any non-approved modes; default-safe behavior documented and enforced. | - | Planning-only: do not enable trading. |
| AT-003 | 1 | `docs/agents.md` responsibilities | TBD | TODO | - | `docs/agents.md` clearly defines agent responsibilities, allowed actions, and escalation paths; referenced by other docs. | - |  |
| AT-101 | 2 | Kill-switch | TBD | TODO | AT-002 | A single kill-switch mechanism exists with documented activation path; on activation, strategy execution is prevented. | - | Planning-only: do not enable trading. |
| AT-102 | 2 | Health contracts | TBD | TODO | - | System components publish/validate health contracts; contract schema documented; failures are actionable. | - |  |
| AT-103 | 2 | Marketdata stale ⇒ no strategies | TBD | TODO | AT-102 | If marketdata is stale/unhealthy, strategy execution is blocked; criteria are documented and tested. | - | Planning-only: do not enable trading. |
| AT-104 | 2 | Deploy report generator | TBD | TODO | - | A deterministic deploy report is generated from repo state; includes version/commit, config, and checks. | - |  |
| AT-105 | 2 | Pre-deploy guard | TBD | TODO | AT-104 | Pre-deploy checks gate deployments; failures provide clear remediation guidance. | - |  |
| AT-201 | 3 | Pub/Sub event bus | TBD | TODO | - | Event bus interfaces and topics are specified; message contracts documented; non-goals/rollout plan defined. | - |  |
| AT-202 | 3 | Formal agent state machine | TBD | TODO | AT-003 | Agent lifecycle states are defined with transitions, invariants, and auditability requirements. | - |  |
| AT-203 | 3 | Post-mortem replay | TBD | TODO | AT-001, AT-201 | Replay inputs/outputs are specified; ability to reproduce runs from artifacts is defined and documented. | - |  |
<!-- TASKS_END -->

