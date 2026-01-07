# Agent Mesh (Autonomy Boundaries + Allowed Operations)

This document defines what **autonomous agents** may and may not do while AgentTrader v2 is production-locked.

## Locked defaults (must remain true)

- Execution is **DISABLED**
- `AGENT_MODE` defaults **OFF**
- Kill-switch defaults **SAFE/HALTED**

## Allowed autonomous actions

- Read-only inspection of repo state, configs, and manifests
- Run readiness checks and produce reports
- Produce audit packs and evidence indexes
- Generate change proposals (diffs/text) for human review

## Forbidden autonomous actions

- Any change that enables execution (`AGENT_MODE=EXECUTE` or equivalent)
- Any change that weakens kill-switch defaults (HALTED -> allowed)
- Any production deploy/apply/scale operation

## Human-only controls

- Approving controlled unlocks (sign-off recorded in-repo)
- Production deployments/releases
- Changing safety defaults

