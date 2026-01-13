# Local Connectivity Standard (Ops UI ↔ Mission Control)

This document defines the canonical **LOCAL DEV** connectivity contract between:

- **Ops UI**: `frontend/ops-ui` (browser app)
- **Mission Control**: `backend/mission_control` (FastAPI API)

## Actual ports (code-truth)

- **Ops UI (Vite dev server)**: **8090**
  - Source of truth: `frontend/ops-ui/package.json` (`vite --port 8090`) and `frontend/ops-ui/vite.config.ts` (`server.port = 8090`).
- **Mission Control (uvicorn/FastAPI)**: **8080**
  - Source of truth: `backend/mission_control/Dockerfile` (`--port 8080`) and `backend/mission_control/README.md` (local run uses `--port 8080`).

## Docs vs code (known drift)

- **Ops UI local-run docs** previously suggested:
  - running from `frontend/` with an `npm run dev:ops-ui` script (there is no `frontend/package.json` in this repo)
  - setting `VITE_MISSION_CONTROL_BASE_URL="http://localhost:8081"` (Mission Control is consistently 8080 in code)
- **Mission Control** docs and Dockerfile match on **8080**.

## CORS behavior (Mission Control)

- **Mission Control does not configure CORS**.
  - Source of truth: `backend/mission_control/main.py` has no `CORSMiddleware` and no `Access-Control-Allow-*` logic.

### What breaks if origins differ?

If Ops UI runs at `http://localhost:8090` and you point it directly at `http://localhost:8080`, the browser will treat that as **cross-origin**. Because Mission Control does not return CORS headers:

- **Browser fetches will fail** with CORS errors (blocked before your app sees a response), including:
  - `GET /ops/status`
  - `GET /api/v1/events/recent`
  - `GET /api/v1/reports/deploy/latest`

## Recommended local-dev pattern (ONE standard): same-origin proxy

Use a **dev proxy** so the browser stays on a single origin (Ops UI), and the dev server proxies API calls to Mission Control.

### Standard behavior

- **Ops UI origin**: `http://localhost:8090`
- **Mission Control**: `http://127.0.0.1:8080`
- **API base URL in the browser**: **`/mission-control`**
- **Proxy mapping**:
  - Browser calls: `http://localhost:8090/mission-control/<path>`
  - Vite proxies to: `http://127.0.0.1:8080/<path>`

### Why this standard?

- **No CORS changes required** in Mission Control for local dev
- **Closer to production** patterns where a single edge (nginx/ingress) fronts both UI and API
- Avoids relying on in-cluster DNS names (which browsers can’t resolve)

## Env vars / configuration contract

### Ops UI (`frontend/ops-ui`)

**Build/dev-time (Vite)**:

- **`VITE_MISSION_CONTROL_BASE_URL`** (optional)
  - **Recommended local default**: omit (Ops UI will use `/mission-control` in dev)
  - If set, examples:
    - `VITE_MISSION_CONTROL_BASE_URL=/mission-control` (works with proxy)
    - `VITE_MISSION_CONTROL_BASE_URL=http://127.0.0.1:8080` (**requires CORS**, not recommended)

**Runtime config (`config.js`)**:

- **`window.__OPS_DASHBOARD_CONFIG__.missionControlBaseUrl`** (preferred)
- **`window.__OPS_UI_CONFIG__.missionControlBaseUrl`** (legacy alias; still supported)

### Mission Control (`backend/mission_control`)

- `AGENTS_CONFIG_PATH` (default `/app/configs/agents/agents.yaml`)
- `POLL_INTERVAL_SECONDS` (default `10`)
- `PER_AGENT_TIMEOUT_SECONDS` (default `1.5`)
- `DEPLOY_REPORT_PATH` (default `/var/agenttrader/reports/deploy_report.md`)

## What must be true for Ops UI to work in a browser

- **Mission Control must be reachable** from the browser’s point of view:
  - either **same-origin** via proxy (recommended), or
  - cross-origin **with explicit CORS** enabled on Mission Control.
- **Ops UI must resolve a usable base URL** for Mission Control:
  - Local dev standard: `missionControlBaseUrl = "/mission-control"`
- **Mission Control must be running** and listening on `127.0.0.1:8080` (or your chosen target).

## Known pitfalls

- **Using `http://agenttrader-mission-control` in a browser**:
  - That name may work inside a cluster/Pod DNS, but your laptop/browser won’t resolve it by default.
- **Cross-origin without CORS**:
  - Pointing Ops UI at `http://localhost:8080` directly will fail in browsers unless Mission Control is updated to allow the Ops UI origin.
- **Port confusion (`8081`)**:
  - Mission Control is 8080 in code; treat any `8081` local-dev instructions as stale.

