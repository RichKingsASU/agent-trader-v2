# AgentTrader v2 — Production Readiness “Go/No-Go” Checklist (Institutional)

This document is the **single source of truth** for determining whether AgentTrader v2 is production-ready for a trading day.

**Safety posture (non-negotiable)**
- **Trading execution must remain disabled by default.**
- **Kill switch must be ON by default** (execution halted) unless explicitly authorized for a controlled window.
- Readiness is **fail-closed**: if a required signal cannot be validated, the outcome is **NO-GO**.

**Primary automation**
- Run `./scripts/readiness_check.sh` to produce auditable artifacts and a deterministic **GO/NO-GO** decision.

**Defaults assumed by this repo**
- **Namespace**: `trading-floor`
- **Kill switch ConfigMap**: `agenttrader-kill-switch` with key `EXECUTION_HALTED`
- **v2 labels**: `app.kubernetes.io/part-of=agent-trader-v2` and `version=v2`

---

## Decision rule (deterministic)

**GO (READY)** only when **all required checks** in sections A–E are **PASS**.

**NO-GO (NOT READY)** when **any required check** is **FAIL** or **UNKNOWN**.

**Evidence requirement**: every check must produce evidence (command output captured in the readiness report), or be explicitly marked as **NOT READY** with an explanation.

---

## A) Build Integrity (Required)

- **No `:latest` tags anywhere in deployable definitions**
  - **PASS**: no `:latest` usage in Kubernetes manifests / Cloud Build configs / Docker references.
  - **FAIL**: any `:latest` detected.

- **Build fingerprints present (GIT SHA / BUILD ID)**
  - **PASS**: workloads include an immutable build identifier (at minimum: `git_sha` label and/or `GIT_SHA` env), and CI provides a build ID (e.g., `BUILD_ID`) surfaced in workload env/labels/annotations.
  - **FAIL**: cannot attribute a running workload to a specific commit/build.

- **Images exist (and are pullable)**
  - **PASS**: running pods show a resolved `imageID` digest and are not failing with image pull errors.
  - **FAIL**: `ImagePullBackOff`, `ErrImagePull`, missing digest, or cannot validate cluster state.

---

## B) Safety & Controls (Required)

- **AGENT_MODE defaults OFF everywhere**
  - **PASS**: `AGENT_MODE` is absent or set to a non-executing mode (`DISABLED`, `WARMUP`, `HALTED`, etc.) across workloads.
  - **FAIL**: any workload is configured with `AGENT_MODE=LIVE` (or any equivalent “EXECUTE” mode).

- **Kill switch defaults ON (execution halted)**
  - **PASS**: `EXECUTION_HALTED=1` in `ConfigMap/agenttrader-kill-switch` **at rest** (baseline), and all execution-capable components mount/read it.
  - **FAIL**: missing kill switch config, or value not `1`, or workloads don’t reference it.

- **Stale-marketdata gating is active**
  - **PASS**: marketdata freshness is enforced fail-closed (e.g., `/healthz` heartbeat contract + consumers refuse to proceed on stale/unreachable marketdata), and no debug bypass is enabled.
  - **FAIL**: bypass env enabled (e.g., `MARKETDATA_HEALTH_CHECK_DISABLED=1`) or freshness contract not enforced.

- **Execution agents disabled (scaled 0 and/or not deployed)**
  - **PASS**: no execution agents are deployed, or replicas are `0`, or they are demonstrably non-executing (dry-run + kill switch ON + non-LIVE mode).
  - **FAIL**: any execution-capable workload is running with replicas > 0 without explicit authorization and documented controls.

---

## C) Health & Observability (Required)

- **Operational status endpoint reachable**
  - **PASS**: `/ops/status` is reachable for marketdata and strategy workloads (or the designated strategy service), and returns an unambiguous status payload.
  - **FAIL**: endpoint missing/unreachable or returns error.

- **Health probes configured**
  - **PASS**: readiness and liveness probes exist for all long-running workloads.
  - **FAIL**: missing probes (or probes failing).

- **Structured logs with correlation**
  - **PASS**: HTTP services emit structured logs that include `correlation_id` (or `x-correlation-id`) for request-scoped events, plus identity fields (service/workload/git SHA).
  - **FAIL**: cannot correlate actions to a request/workflow.

- **Deploy report generator available**
  - **PASS**: `./scripts/report_v2_deploy.sh` produces `audit_artifacts/deploy_report.{md,json}` and is used as deployment evidence.
  - **FAIL**: report generator missing or failing.

---

## D) Infrastructure & Capacity (Required)

- **Resource headroom is adequate**
  - **PASS**: nodes/pods show acceptable headroom; no sustained CPU/memory pressure; critical workloads have sane requests/limits.
  - **FAIL**: insufficient capacity or unstable scheduling.

- **No CrashLoopBackOff / ImagePullBackOff**
  - **PASS**: no v2 pods are in crash or image pull backoff states.
  - **FAIL**: any v2 pod is crash-looping or cannot pull images.

- **Stable service discovery**
  - **PASS**: v2 services are `ClusterIP` (or explicitly documented exceptions) and selectors resolve to ready pods.
  - **FAIL**: missing services, selector mismatches, or broken discovery.

---

## E) Change Control (Required)

- **Last Known Good (LKG) captured**
  - **PASS**: a concrete LKG reference exists (git tag/sha + deploy report), captured **before market open**.
  - **FAIL**: no known rollback anchor.

- **Rollback procedure documented**
  - **PASS**: a deterministic rollback path exists and is documented (what to roll back, how to validate, and how to prove kill switch remains ON).
  - **FAIL**: rollback is ambiguous or requires guesswork.

---

## Canonical commands

- **Readiness gate (audited)**:

```bash
./scripts/readiness_check.sh
```

- **Deploy report (audited)**:

```bash
./scripts/report_v2_deploy.sh
```

- **Kill switch read**:

```bash
kubectl -n trading-floor get configmap agenttrader-kill-switch -o jsonpath='{.data.EXECUTION_HALTED}{"\n"}'
```

- **Kill switch enable (halt execution)**:

```bash
kubectl -n trading-floor patch configmap agenttrader-kill-switch --type merge -p '{"data":{"EXECUTION_HALTED":"1"}}'
```

