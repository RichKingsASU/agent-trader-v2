# AgentTrader v2 — Pre-Market Runbook (Institutional)

**Intent**: deterministically confirm that v2 is safe to run in production **before market open**, with execution disabled unless explicitly authorized.

**Hard rules**
- Do **not** enable execution as part of this runbook.
- If any check cannot be validated, treat as **NO-GO**.

Assumptions:
- Namespace: `trading-floor`
- Kill switch ConfigMap: `agenttrader-kill-switch`

---

## 0) Identify the change being evaluated (required)

```bash
git rev-parse HEAD
git status --porcelain
```

Expected:
- clean working tree for an institutional run

---

## 1) Run deterministic readiness gate (required)

```bash
./scripts/readiness_check.sh
```

Expected:
- exit code `0` for READY
- reports written to `audit_artifacts/readiness_report.{md,json}`

If it exits non-zero: **NO-GO**.

---

## 2) Confirm kill switch state (required, must be ON by default)

Read current value:

```bash
kubectl -n trading-floor get configmap agenttrader-kill-switch -o jsonpath='{.data.EXECUTION_HALTED}{"\n"}'
```

Expected (baseline):
- `1` (execution halted)

If it is `0`: **NO-GO** until explicitly authorized and documented.

---

## 3) Confirm marketdata freshness contract (required)

### 3a) Validate marketdata service responds (in-cluster)

```bash
kubectl -n trading-floor get svc marketdata-mcp-server
kubectl -n trading-floor run readiness-curl --rm -i --restart=Never --image=curlimages/curl:8.5.0 -- \
  sh -lc 'set -e; curl -fsS "http://marketdata-mcp-server/healthz"; echo'
```

Expected:
- HTTP 200
- JSON includes `"ok": true` and a recent `last_tick_epoch_seconds`

### 3b) Confirm no staleness bypass is enabled

```bash
kubectl -n trading-floor get deploy,sts -o yaml | rg -n "MARKETDATA_HEALTH_CHECK_DISABLED|MARKETDATA_FORCE_STALE"
```

Expected:
- no `MARKETDATA_HEALTH_CHECK_DISABLED=1`
- no `MARKETDATA_FORCE_STALE=1`

---

## 4) Confirm strategy posture is non-executing (required)

### 4a) Confirm `AGENT_MODE` is not LIVE/EXECUTE

```bash
kubectl -n trading-floor get deploy,sts -o yaml | rg -n "AGENT_MODE|LIVE|EXECUTE"
```

Expected:
- no workload configured with `AGENT_MODE=LIVE` (or equivalent EXECUTE mode)

### 4b) Confirm strategy pods are healthy and stable

```bash
kubectl -n trading-floor get pods -o wide
kubectl -n trading-floor describe pods | rg -n "CrashLoopBackOff|ImagePullBackOff|ErrImagePull"
```

Expected:
- no crash loops
- no image pull failures

---

## 5) Confirm proposals/decisions are being emitted (optional but recommended)

If the strategy runtime emits decisions to logs or Firestore, validate at least one recent decision event.

Examples (logs):

```bash
kubectl -n trading-floor logs statefulset/gamma-strategy --tail=200
kubectl -n trading-floor logs statefulset/whale-strategy --tail=200
```

Expected:
- recent “decision/proposal” events with clear reasons
- no broker-side execution attempts

---

## 6) Capture Last Known Good (LKG) reference before market open (required)

### 6a) Generate deploy report evidence

```bash
./scripts/report_v2_deploy.sh --namespace trading-floor
```

### 6b) Create a release tag (recommended)

```bash
./scripts/tag_release.sh
```

Expected:
- local git tag like `v2-release-YYYYMMDD-HHMM`
- does **not** push automatically

---

## 7) Final “GO/NO-GO” declaration (required)

Declare **GO** only if:
- readiness gate passed
- kill switch is ON (halted) unless explicitly authorized otherwise
- marketdata is fresh and gating is active
- no workload is configured for LIVE/EXECUTE mode
- cluster health is stable (no crash loops / image pull errors)

