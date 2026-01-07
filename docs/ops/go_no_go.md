# Go / No-Go (Production Change Gate)

This is the human approval gate for **any** production change and **any** controlled unlock described in `ops/PRODUCTION_LOCK.md`.

## Required inputs (attach or link)

- Readiness report (timestamp + git sha)
- Audit pack index (artifact listing)
- Deployment plan (what changes, where, rollback)

## Go criteria (all must be true)

- Execution remains **DISABLED** unless the change is an approved controlled unlock
- Kill-switch default remains **SAFE/HALTED** unless explicitly unlocked
- No manifests set `AGENT_MODE=EXECUTE`
- Health contracts satisfied (see `docs/MARKETDATA_HEALTH_CONTRACT.md`)

## Sign-off template

- Requestor:
- Change/Unlock summary:
- Environments impacted:
- Evidence links:
  - readiness:
  - audit index:
- Approvers:
  - Security:
  - Ops/SRE:
  - Product/Owner:
- Decision:
  - GO / NO-GO
- Notes / constraints:

