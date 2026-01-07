# Runbook: Cluster resource pressure (Pending pods / OOMKilled)

## Safety posture

- Keep execution disabled.
- Prefer reducing non-critical workloads before scaling critical ones.

## Symptoms

- Pods stuck `Pending` (unschedulable)
- Containers terminated with `OOMKilled`
- Node pressure conditions (memory/disk) in events

## Likely causes

- Requests/limits too low or too high
- Node pool insufficient for peak hours
- Noisy neighbor workload consuming resources

## Immediate actions (safe)

1. **Capture artifacts**
   - Run `./scripts/ops_pre_market.sh` to capture pod states and events.
2. **Check events and node conditions**
   - `kubectl -n trading-floor get events --sort-by=.lastTimestamp | tail -n 100`
   - `kubectl get nodes`
3. **Identify offenders**
   - `kubectl -n trading-floor get pods -o wide`
   - If metrics are available: `kubectl top pods -n trading-floor` (best-effort)
4. **Mitigate safely**
   - Reduce/disable non-critical workloads first (manual, recorded change).

## Verification (done when…)

- Pending pods schedule successfully
- No new OOMKilled events
- Core services remain stable during market hours

