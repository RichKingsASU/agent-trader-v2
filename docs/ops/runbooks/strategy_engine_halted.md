# Runbook: Strategy engine halted / refusing to run

## Safety posture

- Strategies must remain **observe-only** (produce proposals, not executions).
- If marketdata is stale, the correct behavior is to refuse to run.

## Symptoms

- Strategy pods are running but not producing expected outputs
- Logs contain “Refusing to run: marketdata_stale” or repeated dependency errors
- Pods restart frequently

## Likely causes

- Marketdata stale (`docs/ops/runbooks/marketdata_stale.md`)
- Kill-switch is active (expected default posture) and strategy code treats it as “halt strategy”
- Missing env vars / misconfigured config
- Downstream persistence unavailable (Firestore/DB) causing crashes

## Immediate actions (safe)

1. **Capture artifacts**
   - Run `./scripts/ops_pre_market.sh` and attach `audit_artifacts/ops_runs/*`.
2. **Check marketdata first**
   - Verify `curl "$MARKETDATA_HEALTH_URL"` returns 200.
3. **Check pod state + events**
   - `kubectl -n trading-floor get pods -l app.kubernetes.io/component=strategy`
   - `kubectl -n trading-floor get events --sort-by=.lastTimestamp | tail -n 50`
4. **Inspect strategy logs**
   - `kubectl -n trading-floor logs statefulset/gamma-strategy --tail=200` (and whale)

## Verification (done when…)

- Strategy runtime is stable (no CrashLoopBackOff)
- Marketdata is healthy
- Strategy outputs resume (proposal artifacts/log markers appear)

