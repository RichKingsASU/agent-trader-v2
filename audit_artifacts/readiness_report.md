## AgentTrader v2 — Readiness Report

- **Generated (UTC)**: 2026-01-07T01:12:09Z
- **Git SHA**: `9aaef69835c138ff931fa77772041f418f57d1fc`
- **Git branch**: `cursor/release-readiness-governance-5548`
- **kubectl context**: `UNKNOWN`
- **namespace**: `trading-floor`

### Overall result: NOT READY (NO-GO)

| Check | Status | Details |
| --- | --- | --- |
| change_control.clean_working_tree | FAIL |  |
| change_control.lkg_tag_present | FAIL |  |
| change_control.repo_id | UNKNOWN |  |
| change_control.origin_remote | PASS |  |
| build.repo_preflight | UNKNOWN |  |
| safety.ci_safety_lint | FAIL |  |
| build.no_latest_tags | PASS |  |
| build.fingerprints_present | FAIL |  |
| cluster.connectivity | FAIL |  |
| cluster.v2_workloads | FAIL |  |
| cluster.health | FAIL |  |
| safety.kill_switch | FAIL |  |
| health.ops_status | FAIL |  |

## Evidence

### git status --porcelain

```text
 M backend/app.py
 M backend/strategy_service/app.py
 M cloudbuild.congressional-ingest.yaml
 M cloudbuild.strategy-engine.yaml
 M cloudbuild.strategy-gamma.yaml
 M cloudbuild.strategy-runtime.yaml
 M cloudbuild.strategy-whale.yaml
 M k8s/05-kill-switch-configmap.yaml
 M k8s/10-gamma-strategy-statefulset.yaml
 M k8s/11-whale-strategy-statefulset.yaml
?? backend/common/http_correlation.py
?? docs/ops/README.md
?? docs/ops/go_no_go.md
?? docs/ops/runbooks/
?? scripts/readiness_check.sh
?? scripts/tag_release.sh
```

### safety lint: verify_risk_management.py

```text

[94m============================================================[0m
[94mRisk Management Kill-Switch Verification[0m
[94m============================================================[0m
[94mℹ[0m Checking implementation completeness...

[94m============================================================[0m
[94m1. Backend Files[0m
[94m============================================================[0m
  [92m✓[0m functions/risk_manager.py exists
  [91m✗[0m   - update_risk_state() function missing
  [92m✓[0m   - calculate_drawdown() function defined
  [91m✗[0m   - get_trading_enabled() function missing
  [92m✓[0m   - Drawdown threshold configured (5%)
  [92m✓[0m functions/main.py exists
  [91m✗[0m   - emergency_liquidate() function missing
  [91m✗[0m   - pulse() missing risk state update
  [91m✗[0m   - risk_manager module not imported
  [92m✓[0m backend/alpaca_signal_trader.py exists
  [91m✗[0m   - Signal generation missing safety check

[94m============================================================[0m
[94m2. Frontend Files[0m
[94m============================================================[0m
  [92m✓[0m frontend/src/components/PanicButton.tsx exists
  [92m✓[0m   - Calls emergency_liquidate Firebase function
  [91m✗[0m   - Double-confirmation missing
  [92m✓[0m frontend/src/components/MasterControlPanel.tsx exists
  [92m✓[0m   - PanicButton integrated
  [92m✓[0m   - PanicButton in header (always visible)
  [92m✓[0m   - Firebase Functions SDK configured

[94m============================================================[0m
[94m3. Configuration[0m
[94m============================================================[0m
  [92m✓[0m firebase-functions in requirements.txt
  [92m✓[0m firebase-admin in requirements.txt

[94m============================================================[0m
[94m4. Documentation[0m
[94m============================================================[0m
  [92m✓[0m Complete documentation available
  [92m✓[0m Quick start guide available

[94m============================================================[0m
[94mVerification Summary[0m
[94m============================================================[0m

Results: [92m15[0m/22 checks passed (68.2%)

[91m============================================================[0m
[91m✗ IMPLEMENTATION INCOMPLETE - FIX FAILURES ABOVE[0m
[91m============================================================[0m
```

### safety lint: verify_zero_trust.py

```text
Traceback (most recent call last):
  File "/workspace/scripts/verify_zero_trust.py", line 24, in <module>
    import firebase_admin
ModuleNotFoundError: No module named 'firebase_admin'
```

### k8s fingerprint scan (git_sha/GIT_SHA/BUILD_ID)

```text
/workspace/k8s/20-marketdata-mcp-server-deployment-and-service.yaml:8:    git_sha: a2466ec
/workspace/k8s/20-marketdata-mcp-server-deployment-and-service.yaml:23:        git_sha: a2466ec
/workspace/k8s/10-gamma-strategy-statefulset.yaml:22:        git_sha: a2466ec
/workspace/k8s/11-whale-strategy-statefulset.yaml:22:        git_sha: a2466ec
```
