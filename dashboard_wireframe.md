# Firebase Ops Dashboard (Read‑Only Skeleton)

## Goal
Minimal, **read-only** Firebase Hosting dashboard that visualizes Firestore operational state via **realtime listeners** (no custom backend API).

## Firestore collections (expected)
- **`ops_services`**: one document per service (status + heartbeat + version + last error + log links)
- **`ingest_pipelines`**: one document per ingest pipeline (status + lag + throughput)
- **`ops_alerts`**: one document per alert (open/closed + severity + summary)

> The UI is schema-tolerant: it renders common fields if present and falls back gracefully.

## Screens / wireframe

### 1) Overview (`/`)
- **Ops services list (status)**
  - Columns: Service (link), Status, Version, Heartbeat timestamp, Heartbeat age, Last error
- **Ingest pipelines list (status)**
  - Columns: Pipeline, Status, Lag, Throughput
  - Link to Ingest Health
- **Open ops_alerts**
  - Columns: Age, Severity, Summary

### 2) Ingest Health (`/ingest`)
- Pipeline table with operational freshness + performance
  - Columns: Pipeline, Status, Lag, Throughput, Last event timestamp, Last event age, Notes/last error

### 3) Service Detail (`/services/:serviceId`)
- **Heartbeat**
- **Version**
- **Last error**
- **Links to logs** (and optional metrics/traces/runbook)
- Raw Firestore doc JSON for debugging

## Component / file structure (implemented)
All changes are in **`frontend/ops-ui`** (Firebase Hosting serves `frontend/ops-ui/dist` per `firebase.json`).

```
frontend/ops-ui/
  package.json
  tsconfig.json
  public/
    config.js                  # runtime config (optional)
  src/
    firebase.ts                # Firebase init (Firestore + Auth), supports runtime config
    App.tsx                    # routes
    components/
      AuthGate.tsx             # anonymous Firebase Auth (optional) to satisfy Firestore rules
      StatusBadge.tsx          # status rendering (OK/DEGRADED/OFFLINE/UNKNOWN…)
      ErrorBanner.tsx
      JsonBlock.tsx
      Layout.tsx               # top nav
    firestore/
      normalize.ts             # Timestamp/date parsing + safe field access
    hooks/
      useAuthUser.ts           # auth state listener
    pages/
      OverviewFirestorePage.tsx
      IngestHealthPage.tsx
      ServiceDetailPage.tsx
```

## Runtime Firebase configuration (no rebuild)
You can inject Firebase config at runtime via `frontend/ops-ui/public/config.js`:

```js
window.__OPS_DASHBOARD_CONFIG__ = window.__OPS_DASHBOARD_CONFIG__ || {};
window.__OPS_DASHBOARD_CONFIG__.firebase = {
  apiKey: "...",
  authDomain: "...",
  projectId: "...",
  storageBucket: "...",
  messagingSenderId: "...",
  appId: "..."
};
```

The app also supports build-time env vars:
- `VITE_FIREBASE_API_KEY`
- `VITE_FIREBASE_AUTH_DOMAIN`
- `VITE_FIREBASE_PROJECT_ID`
- `VITE_FIREBASE_STORAGE_BUCKET`
- `VITE_FIREBASE_MESSAGING_SENDER_ID`
- `VITE_FIREBASE_APP_ID`

## Example Firestore document shapes (illustrative)

### `ops_services/{serviceId}`
```json
{
  "name": "whale-flow-service",
  "status": "OK",
  "updated_at": "2026-01-08T12:34:56Z",
  "heartbeat_at": "2026-01-08T12:34:50Z",
  "version": "1.7.3",
  "last_error": { "message": "…" , "ts": "2026-01-08T11:00:00Z" },
  "links": {
    "logs": "https://…",
    "grafana": "https://…"
  }
}
```

### `ingest_pipelines/{pipelineId}`
```json
{
  "name": "congressional-ingest",
  "status": "DEGRADED",
  "updated_at": "2026-01-08T12:34:56Z",
  "last_event_at": "2026-01-08T12:33:10Z",
  "lag_seconds": 95,
  "throughput_per_min": 120.5,
  "notes": "Backfilling…"
}
```

### `ops_alerts/{alertId}`
```json
{
  "status": "OPEN",
  "created_at": "2026-01-08T12:00:00Z",
  "severity": "HIGH",
  "summary": "Pipeline lag > 60s",
  "service_id": "whale-flow-service",
  "pipeline_id": "congressional-ingest"
}
```

## Example Firestore realtime queries (TypeScript)
These match the dashboard screens.

### Overview: services list
```ts
import { collection, query, orderBy, limit, onSnapshot } from "firebase/firestore";
import { db } from "./firebase";

const q = query(collection(db, "ops_services"), orderBy("updated_at", "desc"), limit(50));
const unsub = onSnapshot(q, (snap) => {
  const rows = snap.docs.map(d => ({ id: d.id, ...d.data() }));
});
```

### Overview: open alerts
If you have a normalized `status` field and an index, you can filter server-side:
```ts
import { collection, query, where, orderBy, limit, onSnapshot } from "firebase/firestore";

const q = query(
  collection(db, "ops_alerts"),
  where("status", "==", "OPEN"),
  orderBy("created_at", "desc"),
  limit(50)
);
onSnapshot(q, ...);
```

### Service detail: single service doc listener
```ts
import { doc, onSnapshot } from "firebase/firestore";

const ref = doc(db, "ops_services", serviceId);
const unsub = onSnapshot(ref, (snap) => {
  const data = snap.exists() ? snap.data() : null;
});
```

### Ingest health: pipelines list
```ts
import { collection, query, orderBy, limit, onSnapshot } from "firebase/firestore";

const q = query(collection(db, "ingest_pipelines"), orderBy("updated_at", "desc"), limit(200));
onSnapshot(q, ...);
```

## Read-only guardrails
- **No writes**: the UI only uses `onSnapshot`/document reads.
- **No admin actions**: no buttons that mutate Firestore state.
- **Auth**: `AuthGate` uses **anonymous Firebase Auth** only to satisfy common Firestore rules that require authentication.

