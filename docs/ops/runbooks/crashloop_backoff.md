# Runbook: CrashLoopBackOff

## Safety posture

- Keep execution disabled (do not change `EXECUTION_HALTED` or scale execution workloads).
- Prefer rollback to last-known-good image/tag rather than “hotfixing” in prod.

## Symptoms

- Pod shows `CrashLoopBackOff`
- Repeated restarts; readiness never becomes healthy

## Likely causes

- Missing env var / secret mount
- Bad image build or wrong entrypoint
- Runtime exception on startup (config parsing, dependency init)

## Immediate actions (safe)

1. **Capture artifacts**
   - Run `./scripts/ops_pre_market.sh` to capture events, images, and basic status.
2. **Inspect logs**
   - `kubectl -n trading-floor logs <pod> --previous --tail=200`
3. **Inspect events**
   - `kubectl -n trading-floor describe pod <pod>`
4. **Validate config/secret mounts**
   - Confirm expected files exist inside container (paths only; do not print secret content).

## Verification (done when…)

- Pod becomes Ready and stays stable for 10+ minutes
- No new Warning events for the workload

