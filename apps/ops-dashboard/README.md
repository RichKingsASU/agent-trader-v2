# Ops Dashboard (AgentTrader v2)

Read-only operational dashboard for **Mission Control**.

## What it is (and what it is not)

- **Read-only UI**: consumes **GET-only** endpoints from Mission Control.
- **No coupling to execution**: this app does not import or call any trade/execution codepaths.
- **API surface**: uses `VITE_MISSION_CONTROL_BASE_URL` (or runtime `public/config.js`) to point at Mission Control.

## Local development

```bash
cd apps/ops-dashboard
npm install
cp .env.example .env
npm run dev
```

## Build

```bash
cd apps/ops-dashboard
npm install
npm run build
```

Build output is written to `apps/ops-dashboard/dist/`.

## Firebase Hosting deploy

From the repo root (uses the existing `.firebaserc` project selection):

```bash
npm --prefix apps/ops-dashboard install
npm --prefix apps/ops-dashboard run build
firebase deploy --only hosting --config apps/ops-dashboard/firebase.json
```

If you want a dedicated Firebase Hosting site/target for this dashboard, configure it with Firebase CLI (multisite) and then add `site`/`target` in `apps/ops-dashboard/firebase.json`.

## Configuration

- **Build-time**: `VITE_MISSION_CONTROL_BASE_URL` (see `.env.example`).
- **Runtime (optional)**: `apps/ops-dashboard/public/config.js` sets `window.__OPS_UI_CONFIG__.missionControlBaseUrl`.

