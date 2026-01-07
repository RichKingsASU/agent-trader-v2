# AgentTrader v2 — Post-Market Runbook (Institutional)

**Intent**: capture deterministic evidence, export logs for the trading window, and return the system to a conservative (non-executing) posture after market close.

Assumptions:
- Namespace: `trading-floor`
- Kill switch ConfigMap: `agenttrader-kill-switch`

---

## 1) Confirm kill switch remains ON (required)

```bash
kubectl -n trading-floor get configmap agenttrader-kill-switch -o jsonpath='{.data.EXECUTION_HALTED}{"\n"}'
```

Expected:
- `1`

If not `1`: immediately halt via your approved process (outside this document’s scope) and treat as an incident.

---

## 2) Capture end-of-day deploy evidence (required)

Generate a deploy report (snapshot of what was running):

```bash
./scripts/report_v2_deploy.sh --namespace trading-floor
```

Also capture readiness report (if not already captured):

```bash
./scripts/readiness_check.sh || true
```

Artifacts:
- `audit_artifacts/deploy_report.{md,json}`
- `audit_artifacts/readiness_report.{md,json}`

---

## 3) Export logs for the incident window (required)

Set a time window (example values; adjust to your session):

```bash
export NS=trading-floor
export START_UTC="2026-01-07T13:00:00Z"
export END_UTC="2026-01-07T21:00:00Z"
```

Capture pod list + current status:

```bash
kubectl -n "${NS}" get pods -o wide
```

Export logs (repeat per workload as needed):

```bash
kubectl -n "${NS}" logs deploy/marketdata-mcp-server --since-time="${START_UTC}" > "audit_artifacts/marketdata_mcp_server_${START_UTC}_${END_UTC}.log" || true
kubectl -n "${NS}" logs statefulset/gamma-strategy --since-time="${START_UTC}" > "audit_artifacts/gamma_strategy_${START_UTC}_${END_UTC}.log" || true
kubectl -n "${NS}" logs statefulset/whale-strategy --since-time="${START_UTC}" > "audit_artifacts/whale_strategy_${START_UTC}_${END_UTC}.log" || true
```

If the cluster has multiple replicas/pods, export per pod:

```bash
kubectl -n "${NS}" get pods -l app.kubernetes.io/part-of=agent-trader-v2 -o name
```

---

## 4) Postmortem replay / simulation (if a tool exists)

If/when a replay tool exists (not currently detected in this repo), run it here and save outputs into `audit_artifacts/`:
- replay decisions against captured marketdata
- compare emitted proposals vs expected
- verify no broker-side execution occurred

---

## 5) Archive proposals/decisions artifacts (required)

At minimum, archive:
- `audit_artifacts/*` (readiness + deploy reports + exported logs)
- any decision/proposal exports produced by strategy services (if applicable)

Suggested:

```bash
tar -czf "audit_artifacts/post_market_archive_$(date -u +%Y%m%dT%H%M%SZ).tgz" audit_artifacts/
```

---

## 6) Scale nonessential workloads to 0 (recommended, safety-first)

If the environment should return to “closed” posture after market close:

```bash
kubectl -n trading-floor scale statefulset/gamma-strategy --replicas=0
kubectl -n trading-floor scale statefulset/whale-strategy --replicas=0
```

Validate:

```bash
kubectl -n trading-floor get pods -o wide
```

