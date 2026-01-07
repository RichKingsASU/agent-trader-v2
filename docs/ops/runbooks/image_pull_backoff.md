# Runbook: ImagePullBackOff / ErrImagePull

## Safety posture

- This is an availability issue, not a reason to change kill-switch posture.
- Avoid “temporary” image tag changes without a recorded change request.

## Symptoms

- Pods stuck in `ImagePullBackOff` / `ErrImagePull`
- Events show registry auth errors, tag not found, or quota

## Likely causes

- Incorrect image tag or registry path in manifest
- Artifact Registry / GCR auth not configured for workload identity
- Registry quota / rate limiting

## Immediate actions (safe)

1. **Capture artifacts**
   - Run `./scripts/ops_pre_market.sh` and preserve `audit_artifacts/`.
2. **Confirm image reference**
   - Check the manifest and the deploy report (`audit_artifacts/deploy_report.md`).
3. **Check events for exact reason**
   - `kubectl -n trading-floor describe pod <pod>`
4. **Verify workload identity / pull permissions**
   - Confirm the service account has permission to pull the image.

## Verification (done when…)

- Pods pull images successfully and become Ready
- Deploy report shows “ok” (or no longer degraded) for the workload

