# Tomorrow Market-Open Runbook (AgentTrader v2)

**Target session**: **Wed 2026-01-14 (US/Eastern)**  
**Primary objective**: confirm data flow + paper-only execution posture + metrics visibility **before market open**.

This runbook is intentionally **fail-closed**: if any required check can’t be validated, treat as **NO-GO**.

---

## 0) Fast summary (GO/NO-GO gates)

**GO (paper-only) requires all of:**

- **Data seeded** for the UI surfaces we expect to demo/monitor (Sentiment + Whale Flow)
- **Paper execution posture works**:
  - paper broker host enforced (`paper-api.alpaca.markets`)
  - live host forbidden in paper mode
  - execution remains **halted** by default unless explicitly authorized
- **Metrics populate**:
  - `/ops/status` responds 200
  - `/metrics` responds 200 and includes required counters/gauges

**Hard safety rule**: do **not** enable live execution as part of “getting things working”.

Key references:
- `docs/ops/runbooks/pre_market.md` (institutional pre-market gate)
- `docs/RISK_MANAGEMENT_KILLSWITCH.md` (risk system kill-switch + emergency liquidation)
- `docs/SAFE_SHUTDOWN.md` (safe termination + kill-switch behavior)
- `docs/metrics_map.md` (cloud monitoring metrics/alerts)

---

## 1) Start commands (choose your environment)

### A) Kubernetes / production-like environment (recommended)

**Pre-flight snapshot (read-only):**

```bash
./scripts/ops_pre_market.sh
```

**Deterministic readiness gate (required):**

```bash
./scripts/readiness_check.sh --namespace trading-floor
```

**Observability check (required when cluster is reachable):**

```bash
./scripts/verify_observability.sh trading-floor
```

### B) Local “ops endpoints” sanity (no cluster required)

This confirms the in-repo `/metrics` and `/ops/status` implementation can expose the required metric names:

```bash
python3 - <<'PY'
import socket, time, urllib.request
from backend.common.ops_http_server import OpsHttpServer

def free_port():
  s = socket.socket()
  s.bind(("127.0.0.1", 0))
  port = s.getsockname()[1]
  s.close()
  return port

port = free_port()
srv = OpsHttpServer(host="127.0.0.1", port=port, service_name="smoke", status_fn=lambda: {"service_name":"smoke","ok":True})
srv.start()
time.sleep(0.05)

metrics = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2).read().decode("utf-8")
required = ["agent_start_total","errors_total","heartbeat_age_seconds","marketdata_ticks_total","marketdata_stale_total","strategy_cycles_total","strategy_cycles_skipped_total","order_proposals_total","safety_halted_total"]
missing = [m for m in required if m not in metrics]
assert not missing, f"missing required metrics: {missing}"
print("OK: /metrics has required names")
print("OK: /ops/status ->", urllib.request.urlopen(f"http://127.0.0.1:{port}/ops/status", timeout=2).read().decode("utf-8"))
srv.stop()
PY
```

### C) Legacy local demo start (Streamlit)

If you’re using the older Streamlit demo wiring:

```bash
./market_open.sh
```

Notes:
- This starts `functions/maestro_bridge.py` and `functions/dashboard.py` locally.
- This is **not** the same as the Kubernetes v2 runtime used by `scripts/readiness_check.sh`.

---

## 2) Verify: data seeded (required)

### A) Sentiment Heatmap seed

**Target Firestore path** (matches `frontend/src/components/institutional/SentimentHeatmap.tsx`):

- `marketData/sentiment/sectors/{sectorId}`

**Seed command:**

```bash
python3 scripts/seed_sentiment_data.py
```

**Verify (expected: 11 sector docs):**

- In Firestore Console: `marketData/sentiment/sectors`
- Or (programmatic) re-run `python3 scripts/seed_sentiment_data.py` which includes a `verify_data()` readback pass.

### B) Whale Flow seed (tenant-scoped)

**Target Firestore paths** (matches `frontend/src/hooks/useWhaleFlow.ts`):

- `tenants/{TENANT_ID}/market_intelligence/options_flow/live/{autoDocId}`
- `tenants/{TENANT_ID}/ops/system_status` (GEX overlay fields)

**Seed command:**

```bash
python3 scripts/seed_whale_flow_data.py --tenant-id "<TENANT_ID>" --num-trades 50 --num-golden-sweeps 5
```

**Verify:**

- In UI: Whale Flow page should show recent trades and at least one “Golden Sweep” (>$1M premium, <14 DTE).
- In Firestore Console: confirm recent docs exist under the `options_flow/live` collection for the tenant.

---

## 3) Verify: paper execution works (required)

### A) Repo-level safeguards (smoke)

Run the explicit paper execution safeguard tests:

```bash
python3 -m pytest -q tests/test_paper_execution_safeguards.py
```

Expected:
- All tests pass
- Live Alpaca host is blocked when `TRADING_MODE=paper`
- Paper Alpaca host is allowed in paper mode

### B) Execution Agent “paper-only decisions” (optional, recommended)

This agent **does not place orders**; it only emits `APPROVE/REJECT` decision artifacts for proposals:

```bash
mkdir -p /tmp/exec_agent && cat > /tmp/exec_agent/proposals.ndjson <<'EOF'
{"proposal_id":"p-1","valid_until_utc":"2099-01-01T00:00:00Z","requires_human_approval":true,"order":{"symbol":"SPY","side":"buy","qty":1}}
EOF

export REPO_ID="agent-trader-v2"
export AGENT_NAME="execution-agent"
export AGENT_ROLE="execution"
export AGENT_MODE="EXECUTE"
export EXECUTION_AGENT_ENABLED="true"
export BROKER_EXECUTION_ENABLED="false"
export PROPOSALS_PATH="/tmp/exec_agent/proposals.ndjson"
export MARKETDATA_LAST_TS_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 -m backend.execution_agent.main
```

Verify output:
- Look for logs containing `intent_type="execution_decision"`
- Check `audit_artifacts/execution_decisions/<YYYY-MM-DD>/decisions.ndjson`

---

## 4) Verify: metrics populate (required)

### A) Kubernetes (in-cluster)

```bash
./scripts/verify_observability.sh trading-floor
```

Minimum acceptable:
- `marketdata-mcp-server` `/ops/status` returns 200
- `/metrics` returns 200
- `/metrics` contains (at least) these names:
  - `agent_start_total`
  - `errors_total`
  - `heartbeat_age_seconds`
  - `marketdata_ticks_total`
  - `marketdata_stale_total`
  - `strategy_cycles_total`
  - `strategy_cycles_skipped_total`
  - `order_proposals_total`
  - `safety_halted_total`

### B) What to monitor during the session (high-signal)

**System health:**
- `/ops/status` for each critical service (marketdata + strategy runtimes)
- CrashLoopBackOff / ImagePullBackOff in pods
- “marketdata stale” events (and rising `marketdata_stale_total`)

**Freshness / lag:**
- Pub/Sub subscription `oldest_unacked_message_age`
- Pub/Sub `num_undelivered_messages`
- Cloud Run request volume + 4xx/5xx (where applicable)

**Error rates:**
- Cloud Run 5xx% and 4xx% (consumer endpoints)
- Firestore write errors / latency (if persistence is in play)

Start with: `docs/metrics_map.md` (alert thresholds + mapping).

---

## 5) Kill switch (how to stop safely)

### A) Kubernetes kill switch (default: ON / halted)

**Read current value:**

```bash
kubectl -n trading-floor get configmap agenttrader-kill-switch -o jsonpath='{.data.EXECUTION_HALTED}{"\n"}'
```

**Force halt (recommended “panic stop”):**

```bash
kubectl -n trading-floor patch configmap agenttrader-kill-switch --type merge -p '{"data":{"EXECUTION_HALTED":"1"}}'
```

### B) Application-level emergency liquidation (last resort)

See `docs/RISK_MANAGEMENT_KILLSWITCH.md` (callable function: `emergency_liquidate`).

### C) Safe shutdown / termination

See `docs/SAFE_SHUTDOWN.md`.

---

## 6) End-of-day / post-session capture (recommended)

Capture artifacts for auditability:

```bash
./scripts/ops_pre_market.sh
./scripts/readiness_check.sh --namespace trading-floor
```

Expected outputs:
- `audit_artifacts/ops_runs/<timestamp>_pre_market/*`
- `audit_artifacts/readiness_report.{md,json}`

