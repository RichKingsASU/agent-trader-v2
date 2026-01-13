# Ops UI (Read-only, cluster-internal)

Minimal “calm” dashboard for Mission Control status:

- Overview: overall counts + agent table + recent events + last deploy report snippet
- Agent detail: identity + build fingerprint + redacted ops status JSON + last 50 events
- Deploy report: renders latest `deploy_report.md` as sanitized markdown

## Local run

From the repo:

```bash
cd frontend/ops-ui
npm install
npm run dev
```

Then open `http://localhost:8090`.

### Local connectivity (recommended)

Run Mission Control locally on `http://127.0.0.1:8080` (see `backend/mission_control/README.md`), then run Ops UI.

Ops UI local dev uses a same-origin proxy:

- Browser connects to Ops UI: `http://localhost:8090`
- Ops UI calls Mission Control via: `GET /mission-control/...`
- Vite proxies `/mission-control/*` → `http://127.0.0.1:8080/*`

This avoids CORS requirements in Mission Control during local dev.

### Overriding the API base URL

If you are not using the proxy (or you have Mission Control elsewhere), set:

```bash
cd frontend/ops-ui
VITE_MISSION_CONTROL_BASE_URL="http://127.0.0.1:8080" npm run dev
```

## Build

```bash
cd frontend/ops-ui
npm ci
npm run build
```

This builds:
- `frontend/ops-ui/` (Ops UI)

## Firebase Hosting deploy (optional)

If you want to host Ops UI publicly via Firebase Hosting (instead of the cluster-internal nginx container), see:
- `docs/ops/firebase_ops_dashboard_deploy.md`

## Container image (nginx static site)

Build the Ops UI image from repo root:

```bash
docker build -f frontend/ops-ui/Dockerfile -t <your-registry>/agenttrader-ops-ui:<tag> .
docker push <your-registry>/agenttrader-ops-ui:<tag>
```

At runtime, you can set `VITE_MISSION_CONTROL_BASE_URL` on the container to generate `/config.js` for the UI.

## Deploy to cluster (ClusterIP only)

Edit `k8s/ops-ui/deployment.yaml` to point at your pushed image tag, then:

```bash
kubectl apply -f k8s/ops-ui/deployment.yaml
kubectl apply -f k8s/ops-ui/service.yaml
```

## Access (port-forward)

```bash
kubectl -n trading-floor port-forward svc/agenttrader-ops-ui 8080:80
```

Then open `http://localhost:8080`.

