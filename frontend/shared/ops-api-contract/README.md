## `ops-api-contract` (shared TypeScript types)

Single source of truth for the **read-only** Ops API contract used by:
- `frontend/ops-ui` (ops-dashboard UI)
- `frontend` (main UI, if/when it needs ops surfaces)

### What’s in here
- Service-level `/ops/status` types (`OpsStatus`, `OpsState`, ...)
- Mission Control aggregated `/ops/status` types (`MissionControlOpsStatusResponse`, ...)
- `/ops/health` response type

### Usage
- In `frontend/ops-ui`, import from `@ops-contract` (wired via `vite.config.ts` alias).

