## Agents Runbook (Production)

### RUNBOOK CHECK (use this during an incident)
- **Triage**: identify scope (data stale vs execution vs strategy runtime).
- **Verify minimal stack** is healthy (section below) before touching strategy replicas.
- **Grab logs + events** for the failing workload(s); classify into: CrashLoopBackOff / ImagePullBackOff / stale data.
- **Apply the smallest safe action**: restart one pod, roll out one workload, or scale down a strategy to `0` to stop impact.
- **Confirm kill switches** (execution + risk) are in the intended state before re-enabling strategies.

---

### Agent inventory (one line per agent)

| Agent / service | Purpose | Authority | Dependencies | Scaling notes |
|---|---|---|---|
| `marketdata-mcp-server` (K8s `Deployment`, ns `trading-floor`) | Serve market/broker data to other components via MCP | **Read** market/broker data; no trade placement | K8s `trader-secrets` (`APCA_API_KEY_ID`, `FIREBASE_KEY`), Firestore, Alpaca | Can scale horizontally if stateless; verify no per-pod state/caching assumptions. |
| `gamma-strategy` (K8s `StatefulSet`) | Strategy runtime (gamma strategy) | Emits **order intents/signals**; should not place trades directly | Market data source (typically MCP + Firestore), strategy runtime image | Keep at **1 replica** unless you have leader election/partitioning (avoid duplicate signals/orders). |
| `whale-strategy` (K8s `StatefulSet`) | Strategy runtime (whale flow strategy) | Emits **order intents/signals**; should not place trades directly | Market data source (typically MCP + Firestore), strategy runtime image | Keep at **1 replica** unless you have leader election/partitioning (avoid duplicate signals/orders). |
| `market-ingest` (Cloud Run service) | Live market data ingestion (websocket loop + `/health`) | **Read** market data, writes freshness/state downstream | Firestore (`FIREBASE_PROJECT_ID`), Alpaca (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`) | `minScale=1,maxScale=1` by template. Do not scale >1 unless your ingestion pipeline is idempotent. |
| `execution-engine` (Cloud Run service) | Validates intents + routes orders (or dry-run) | **Can place trades** when not dry-run and kill-switch allows | Firestore (`FIREBASE_PROJECT_ID`), Alpaca keys (if live), Postgres (`DATABASE_URL`) for position sizing/risk | Can autoscale; ensure idempotency via `client_order_id` and enforce kill switches. |
| `alpaca-bars-backfill` (Cloud Run job, optional) | Backfill historical bars | Writes data to DB | Postgres (`DATABASE_URL`), Alpaca keys | Batch job; run manually or via scheduler. Avoid concurrent runs unless safe. |
| Cloud Functions: `generate_trading_signal()` | Orchestrates multi-strategy evaluation + persists signals / shadow trades | **No live trades** (shadow by design) | Firestore, Alpaca market/account read | Scales automatically; protect with rate limits and kill-switch (`trading_enabled`). |
| Cloud Functions: `pulse()` (scheduled) | Periodic risk + shadow P&L updates | Updates risk flags + shadow P&L | Firestore, Alpaca market/account read | If delayed/failed, data becomes stale quickly; prioritize restoring schedule. |

---

### Minimal viable stack (what must be running today)

- **Storage + flags**
  - **Firestore**: required for signals, shadow trades, risk state, and execution ledger.
  - **Risk kill-switch doc**: `systemStatus/risk_management` (must be reachable; `trading_enabled` should be correct).
- **Market data freshness path**
  - **Cloud Run `market-ingest`**: required for “fresh” market data in most live setups.
  - **K8s `marketdata-mcp-server`**: required if strategies/UI depend on MCP market data.
- **Strategy evaluation path (as needed)**
  - **K8s `gamma-strategy` / `whale-strategy`**: only if those strategies are enabled.
- **Trade execution path (only if live trading is enabled)**
  - **Cloud Run `execution-engine`**: must be up; confirm `EXEC_DRY_RUN` and kill switches before enabling.

---

### Standard kubectl commands (K8s namespace: `trading-floor`)

```bash
# Status (what's running + where)
kubectl -n trading-floor get deploy,sts,pods,svc -o wide
kubectl -n trading-floor get events --sort-by=.lastTimestamp | tail -n 50

# Describe (why it's failing)
kubectl -n trading-floor describe pod/<pod-name>

# Logs
kubectl -n trading-floor logs deploy/marketdata-mcp-server --tail=200
kubectl -n trading-floor logs deploy/marketdata-mcp-server --tail=200 -f
kubectl -n trading-floor logs sts/gamma-strategy --tail=200
kubectl -n trading-floor logs sts/whale-strategy --tail=200

# Restart (safe first step for transient failures)
kubectl -n trading-floor rollout restart deploy/marketdata-mcp-server
kubectl -n trading-floor rollout restart sts/gamma-strategy
kubectl -n trading-floor rollout restart sts/whale-strategy

# Rollout status (wait for recovery)
kubectl -n trading-floor rollout status deploy/marketdata-mcp-server --timeout=120s
kubectl -n trading-floor rollout status sts/gamma-strategy --timeout=120s
kubectl -n trading-floor rollout status sts/whale-strategy --timeout=120s

# Scale
kubectl -n trading-floor scale deploy/marketdata-mcp-server --replicas=2
kubectl -n trading-floor scale sts/gamma-strategy --replicas=0   # stop strategy quickly
kubectl -n trading-floor scale sts/whale-strategy --replicas=0   # stop strategy quickly
```

---

### Common failure modes (symptoms → checks → actions)

#### CrashLoopBackOff
- **Checks**
  - `kubectl -n trading-floor describe pod/<pod>` (look at: last state, exit code, env/secret errors, OOMKilled)
  - `kubectl -n trading-floor logs <workload> --previous --tail=200`
- **Actions (smallest first)**
  - Rollout restart the specific workload.
  - If OOMKilled: raise memory limits/requests (or reduce workload) before scaling replicas.
  - If config/secret missing: confirm `trader-secrets` exists and keys match expected env vars.

#### ImagePullBackOff / ErrImagePull
- **Checks**
  - `kubectl -n trading-floor describe pod/<pod>` → events show auth vs “not found”.
  - Confirm image tag exists and cluster has permission to pull from Artifact Registry.
- **Actions**
  - Fix image reference (tag/registry) or restore registry access for the node/service account.
  - Prefer rollback to last known-good image/tag if available.

#### Stale data (prices/P&L not updating)
- **Fast signals**
  - UI/strategy sees old timestamps, or P&L `last_pnl_update` lags.
- **Checks**
  - Cloud Run `market-ingest` health + logs (look for websocket disconnects / auth failures).
  - Cloud Function scheduler health for `pulse()` (missed runs/backlog).
  - K8s `marketdata-mcp-server` logs (timeouts to Firestore/Alpaca).
- **Actions**
  - Restore data ingestion first (market-ingest connectivity/keys).
  - Restore scheduled `pulse()` execution (quota/permissions/runtime errors).
  - After freshness recovers, restart strategy pods to clear any stuck caches/connections.

---

### Safe scale-up checklist (enabling strategies)

- **Pre-flight safety**
  - **Execution is fail-safe**: `execution-engine` running with `EXEC_DRY_RUN=1` until explicitly ready.
  - **Kill switches set**:
    - Execution: `EXEC_KILL_SWITCH=1` (or Firestore `ops/execution_kill_switch` enabled) until go-live.
    - Risk: Firestore `systemStatus/risk_management.trading_enabled=false` until go-live.
  - **Secrets validated**: Alpaca keys present (Cloud Run) and `trader-secrets` present (K8s).
- **Data readiness**
  - Market data is **fresh** (no ingest disconnects; timestamps updating).
  - Firestore reads/writes healthy (no permission/quota errors).
- **Enablement plan**
  - Start **one strategy at a time**; keep each strategy at **1 replica**.
  - Canary period: enable for a small symbol set / low allocation / shadow-only first.
  - Watch for duplicates (repeated intents/signals) and latency spikes.
- **Rollback plan (must be ready)**
  - Know the “stop” commands: scale the strategy `StatefulSet` to `0`.
  - Keep execution kill-switch readily toggled (env or Firestore doc).

