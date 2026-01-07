# Ops Dashboard (Canonical)

This repo contains **one canonical read-only ops dashboard** at `frontend/ops-ui/`.

## Local run

```bash
cd frontend
npm install
npm run dev:ops-ui
```

Open `http://localhost:8090`.

## Mission Control base URL

By default, the dashboard calls Mission Control at `http://agenttrader-mission-control`.

Override for local development:

```bash
cd frontend/ops-ui
VITE_MISSION_CONTROL_BASE_URL="http://localhost:8081" npm run dev
```

