#!/usr/bin/env bash
set -euo pipefail

# AgentTrader v2 readiness gate (institutional, fail-closed).
#
# Outputs:
# - audit_artifacts/readiness_report.md
# - audit_artifacts/readiness_report.json
#
# Exit code:
# - 0 => READY
# - non-zero => NOT READY

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/audit_artifacts"
REPORT_MD="${OUT_DIR}/readiness_report.md"
REPORT_JSON="${OUT_DIR}/readiness_report.json"

mkdir -p "${OUT_DIR}"

export KUBECTL_PAGER=""
export PAGER=cat
export GIT_PAGER=cat
export LESS=-FRSX

NS="${NAMESPACE:-trading-floor}"
SKIP_PREFLIGHT="${SKIP_PREFLIGHT:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace|-n)
      NS="${2:-}"
      shift 2
      ;;
    --skip-preflight)
      SKIP_PREFLIGHT="1"
      shift 1
      ;;
    --help|-h)
      cat <<EOF
Usage: ./scripts/readiness_check.sh [--namespace <ns>] [--skip-preflight]

Environment:
  NAMESPACE         Namespace to check (default: trading-floor)
  SKIP_PREFLIGHT    Set to 1 to skip scripts/preflight.sh (default: 0)
EOF
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: missing required command: ${cmd}" >&2
    return 1
  fi
  return 0
}

HAS_RG=0
if command -v rg >/dev/null 2>&1; then
  HAS_RG=1
fi

NOW_UTC="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
GIT_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo "UNKNOWN")"
GIT_BRANCH="$(git -C "${ROOT_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "UNKNOWN")"

TMP_DIR="$(mktemp -d)"
RESULTS_TSV="${TMP_DIR}/results.tsv"
EVIDENCE_MD="${TMP_DIR}/evidence.md"
touch "${RESULTS_TSV}" "${EVIDENCE_MD}"

READY=1

_sanitize_one_line() {
  # collapse newlines and tabs for TSV safety
  python3 - <<'PY'
import sys
s = sys.stdin.read()
s = s.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
print(s)
PY
}

add_result() {
  local name="$1"
  local status="$2" # PASS|FAIL|UNKNOWN
  local details="$3"
  details="$(printf "%s" "${details}" | _sanitize_one_line)"
  printf "%s\t%s\t%s\n" "${name}" "${status}" "${details}" >> "${RESULTS_TSV}"
  if [[ "${status}" != "PASS" ]]; then
    READY=0
  fi
}

append_evidence() {
  local title="$1"
  local body="$2"
  {
    echo
    echo "### ${title}"
    echo
    echo '```text'
    printf "%s\n" "${body}"
    echo '```'
  } >> "${EVIDENCE_MD}"
}

run_and_capture() {
  # Usage: run_and_capture "title" "command..."
  local title="$1"
  shift
  local out
  set +e
  out="$("$@" 2>&1)"
  local rc=$?
  set -e
  append_evidence "${title}" "${out}"
  return "${rc}"
}

# -------------------------
# A) Repo hygiene / guards
# -------------------------

if require_cmd git; then
  if [[ -n "$(git -C "${ROOT_DIR}" status --porcelain 2>/dev/null || true)" ]]; then
    add_result "change_control.clean_working_tree" "FAIL" "working tree is dirty"
    append_evidence "git status --porcelain" "$(git -C "${ROOT_DIR}" status --porcelain 2>&1 || true)"
  else
    add_result "change_control.clean_working_tree" "PASS" "working tree clean"
  fi

  # Last Known Good (LKG): require at least one institutional release tag.
  LKG_TAG="$(git -C "${ROOT_DIR}" tag --list 'v2-release-*' --sort=-creatordate | head -n 1 || true)"
  if [[ -n "${LKG_TAG}" ]]; then
    add_result "change_control.lkg_tag_present" "PASS" "found release tag ${LKG_TAG}"
  else
    add_result "change_control.lkg_tag_present" "FAIL" "no v2-release-* tag found (use scripts/tag_release.sh to capture LKG)"
  fi

  # Predeploy guardrails (read-only): verify repo identity when .repo_id is present.
  if [[ -f "${ROOT_DIR}/.repo_id" ]]; then
    REPO_ID="$(tr -d ' \n\r\t' < "${ROOT_DIR}/.repo_id" || true)"
    if [[ "${REPO_ID}" != "agent-trader-v2" ]]; then
      add_result "change_control.repo_id" "FAIL" ".repo_id mismatch (expected agent-trader-v2, got ${REPO_ID:-empty})"
    else
      add_result "change_control.repo_id" "PASS" ".repo_id matches agent-trader-v2"
    fi
  else
    add_result "change_control.repo_id" "UNKNOWN" "missing .repo_id (deploy_v2.sh expects it)"
  fi

  ORIGIN_URL="$(git -C "${ROOT_DIR}" remote get-url origin 2>/dev/null || true)"
  if [[ -n "${ORIGIN_URL}" && "${ORIGIN_URL}" == *"RichKingsASU/agent-trader-v2"* ]]; then
    add_result "change_control.origin_remote" "PASS" "origin matches expected repo"
  else
    add_result "change_control.origin_remote" "UNKNOWN" "cannot validate origin remote (origin=${ORIGIN_URL:-unknown})"
  fi
else
  add_result "change_control.git_available" "FAIL" "git not available"
fi

# Repo hygiene checks (best-effort, if present)
if [[ "${SKIP_PREFLIGHT}" == "1" ]]; then
  add_result "build.repo_preflight" "UNKNOWN" "skipped (SKIP_PREFLIGHT=1)"
else
  if [[ -f "${ROOT_DIR}/scripts/preflight.sh" ]]; then
    if run_and_capture "scripts/preflight.sh" bash "${ROOT_DIR}/scripts/preflight.sh"; then
      add_result "build.repo_preflight" "PASS" "preflight passed"
    else
      add_result "build.repo_preflight" "FAIL" "preflight failed (see report evidence)"
    fi
  else
    add_result "build.repo_preflight" "UNKNOWN" "scripts/preflight.sh not present"
  fi
fi

# CI safety lint(s) (best-effort, if present)
SAFETY_LINT_OK=1
for candidate in \
  "${ROOT_DIR}/scripts/verify_risk_management.py" \
  "${ROOT_DIR}/scripts/verify_zero_trust.py"
do
  if [[ -f "${candidate}" ]]; then
    if run_and_capture "safety lint: $(basename "${candidate}")" python3 "${candidate}"; then
      :
    else
      SAFETY_LINT_OK=0
    fi
  fi
done
if [[ "${SAFETY_LINT_OK}" == "1" ]]; then
  add_result "safety.ci_safety_lint" "PASS" "safety lint scripts passed (or none present)"
else
  add_result "safety.ci_safety_lint" "FAIL" "one or more safety lint scripts failed"
fi

# ---------------------------------
# A) Build integrity: no ":latest" image tags
# ---------------------------------

LATEST_HITS=""
if command -v rg >/dev/null 2>&1; then
  set +e
  LATEST_HITS="$(rg -n '(\bimage:\s*\S+:latest\b|docker\.pkg\.dev/\S+:latest\b|gcr\.io/\S+:latest\b)' "${ROOT_DIR}/k8s" "${ROOT_DIR}/infra" "${ROOT_DIR}"/cloudbuild*.yaml 2>/dev/null || true)"
  set -e
else
  set +e
  LATEST_HITS="$(git -C "${ROOT_DIR}" grep -n -E '(\bimage:[[:space:]]*[^[:space:]]+:latest\b|docker[.]pkg[.]dev/[^[:space:]]+:latest\b|gcr[.]io/[^[:space:]]+:latest\b)' -- k8s infra cloudbuild*.yaml 2>/dev/null || true)"
  set -e
fi

if [[ -n "${LATEST_HITS}" ]]; then
  add_result "build.no_latest_tags" "FAIL" "found :latest image tag usage"
  append_evidence "latest tag scan" "${LATEST_HITS}"
else
  add_result "build.no_latest_tags" "PASS" "no :latest image tag usage detected"
fi

# Build fingerprints (best-effort from repo manifests)
if [[ "${HAS_RG}" == "1" ]]; then
  FINGERPRINTS="$(rg -n "git_sha:|GIT_SHA|BUILD_ID" "${ROOT_DIR}/k8s" 2>/dev/null || true)"
else
  FINGERPRINTS="$(git -C "${ROOT_DIR}" grep -n -E "git_sha:|GIT_SHA|BUILD_ID" -- k8s 2>/dev/null || true)"
fi
if [[ -z "${FINGERPRINTS}" ]]; then
  add_result "build.fingerprints_present" "FAIL" "no git_sha/GIT_SHA/BUILD_ID found in k8s manifests"
else
  if printf "%s" "${FINGERPRINTS}" | python3 - <<'PY'
import re,sys
sys.exit(0 if re.search(r"\bBUILD_ID\b", sys.stdin.read()) else 2)
PY
  then
    add_result "build.fingerprints_present" "PASS" "build fingerprints detected (git_sha and BUILD_ID present)"
  else
    add_result "build.fingerprints_present" "FAIL" "BUILD_ID not surfaced in k8s manifests (git_sha present, but build id missing)"
  fi
  append_evidence "k8s fingerprint scan (git_sha/GIT_SHA/BUILD_ID)" "${FINGERPRINTS}"
fi

# -------------------------
# Cluster connectivity
# -------------------------

CLUSTER_OK=1
KUBE_CONTEXT="UNKNOWN"
if require_cmd kubectl; then
  KUBE_CONTEXT="$(kubectl config current-context 2>/dev/null || echo "UNKNOWN")"
  if ! kubectl get namespace "${NS}" >/dev/null 2>&1; then
    CLUSTER_OK=0
  fi
else
  CLUSTER_OK=0
fi

if [[ "${CLUSTER_OK}" != "1" ]]; then
  add_result "cluster.connectivity" "FAIL" "cannot reach cluster/namespace (context=${KUBE_CONTEXT}, namespace=${NS})"
  # Fail-safe: cluster-dependent checks are NOT READY.
  add_result "cluster.v2_workloads" "FAIL" "cluster unreachable; cannot validate workloads"
  add_result "cluster.health" "FAIL" "cluster unreachable; cannot validate pod health"
  add_result "safety.kill_switch" "FAIL" "cluster unreachable; cannot validate kill switch state"
  add_result "health.ops_status" "FAIL" "cluster unreachable; cannot validate /ops/status"
else
  add_result "cluster.connectivity" "PASS" "cluster reachable (context=${KUBE_CONTEXT}, namespace=${NS})"
fi

# -------------------------
# Cluster checks (best-effort, fail-closed if reachable)
# -------------------------

if [[ "${CLUSTER_OK}" == "1" ]]; then
  # List v2 workloads
  V2_LIST="$(kubectl -n "${NS}" get deploy,sts,svc -l app.kubernetes.io/part-of=agent-trader-v2 -o wide 2>&1 || true)"
  append_evidence "v2 workloads (deploy,sts,svc)" "${V2_LIST}"
  if printf "%s" "${V2_LIST}" | python3 - <<'PY'
import sys
sys.exit(0 if "No resources found" in sys.stdin.read() else 2)
PY
  then
    add_result "cluster.v2_workloads" "FAIL" "no v2 workloads discovered in namespace ${NS}"
  else
    add_result "cluster.v2_workloads" "PASS" "v2 workloads discovered"
  fi

  # Replicas/ready (deploy + sts)
  REPL_FAIL=0
  DEP_LINES="$(kubectl -n "${NS}" get deploy -l app.kubernetes.io/part-of=agent-trader-v2 -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.readyReplicas}{"\t"}{.spec.replicas}{"\n"}{end}' 2>/dev/null || true)"
  STS_LINES="$(kubectl -n "${NS}" get sts -l app.kubernetes.io/part-of=agent-trader-v2 -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.readyReplicas}{"\t"}{.spec.replicas}{"\n"}{end}' 2>/dev/null || true)"
  append_evidence "replicas readiness (deployments)" "${DEP_LINES:-<none>}"
  append_evidence "replicas readiness (statefulsets)" "${STS_LINES:-<none>}"
  while IFS=$'\t' read -r name ready desired; do
    [[ -z "${name}" ]] && continue
    ready="${ready:-0}"
    desired="${desired:-0}"
    if [[ "${ready}" != "${desired}" ]]; then
      REPL_FAIL=1
    fi
  done <<< "${DEP_LINES}"
  while IFS=$'\t' read -r name ready desired; do
    [[ -z "${name}" ]] && continue
    ready="${ready:-0}"
    desired="${desired:-0}"
    if [[ "${ready}" != "${desired}" ]]; then
      REPL_FAIL=1
    fi
  done <<< "${STS_LINES}"
  if [[ "${REPL_FAIL}" == "1" ]]; then
    add_result "cluster.replicas_ready" "FAIL" "one or more workloads not fully ready"
  else
    add_result "cluster.replicas_ready" "PASS" "all discovered workloads are fully ready"
  fi

  # CrashLoopBackOff / ImagePullBackOff / ErrImagePull
  PODS_WIDE="$(kubectl -n "${NS}" get pods -l app.kubernetes.io/part-of=agent-trader-v2 -o wide 2>&1 || true)"
  append_evidence "pods (wide)" "${PODS_WIDE}"
  if printf "%s" "${PODS_WIDE}" | python3 - <<'PY'
import re,sys
sys.exit(0 if re.search(r"(CrashLoopBackOff|ImagePullBackOff|ErrImagePull)", sys.stdin.read()) else 2)
PY
  then
    add_result "cluster.no_crash_or_pull_backoff" "FAIL" "crash loop or image pull backoff detected"
  else
    add_result "cluster.no_crash_or_pull_backoff" "PASS" "no crash loop or image pull backoff detected"
  fi

  # Images exist (evidence: imageID digests present on pods)
  POD_IMAGES="$(kubectl -n "${NS}" get pods -l app.kubernetes.io/part-of=agent-trader-v2 -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{range .status.containerStatuses[*]}{"  "}{.name}{" image="}{.image}{" imageID="}{.imageID}{"\n"}{end}{end}' 2>/dev/null || true)"
  append_evidence "pod images (imageID evidence)" "${POD_IMAGES:-<none>}"
  if [[ -z "${POD_IMAGES}" ]] || printf "%s" "${POD_IMAGES}" | rg -q "imageID=$"; then
    add_result "build.images_exist" "FAIL" "cannot verify image digests (imageID missing)"
  else
    add_result "build.images_exist" "PASS" "pod image digests observed (imageID present)"
  fi

  # Probes exist on long-running workloads
  PROBE_FAIL=0
  for kind in deploy sts; do
    NAMES="$(kubectl -n "${NS}" get "${kind}" -l app.kubernetes.io/part-of=agent-trader-v2 -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)"
    while IFS= read -r name; do
      [[ -z "${name}" ]] && continue
      YAML="$(kubectl -n "${NS}" get "${kind}" "${name}" -o yaml 2>/dev/null || true)"
      if ! printf "%s" "${YAML}" | python3 - <<'PY'
import sys
sys.exit(0 if "readinessProbe:" in sys.stdin.read() else 2)
PY
      then
        PROBE_FAIL=1
      fi
      if ! printf "%s" "${YAML}" | python3 - <<'PY'
import sys
sys.exit(0 if "livenessProbe:" in sys.stdin.read() else 2)
PY
      then
        PROBE_FAIL=1
      fi
    done <<< "${NAMES}"
  done
  if [[ "${PROBE_FAIL}" == "1" ]]; then
    add_result "health.probes_configured" "FAIL" "one or more v2 workloads missing readiness/liveness probes"
  else
    add_result "health.probes_configured" "PASS" "readiness/liveness probes present on discovered workloads"
  fi

  # AGENT_MODE must not be LIVE/EXECUTE anywhere
  MANIFEST_YAML="$(kubectl -n "${NS}" get deploy,sts -l app.kubernetes.io/part-of=agent-trader-v2 -o yaml 2>/dev/null || true)"
  if [[ "${HAS_RG}" == "1" ]]; then
    append_evidence "workload env scan (AGENT_MODE)" "$(printf "%s" "${MANIFEST_YAML}" | rg -n "AGENT_MODE|EXECUTE|LIVE" || true)"
  else
    append_evidence "workload env scan (AGENT_MODE)" "$(printf "%s" "${MANIFEST_YAML}" | python3 - <<'PY'
import re,sys
for i, line in enumerate(sys.stdin.read().splitlines(), start=1):
    if re.search(r"(AGENT_MODE|EXECUTE|LIVE)", line):
        print(f"{i}:{line}")
PY
)"
  fi
  if printf "%s" "${MANIFEST_YAML}" | python3 - <<'PY'
import re
import sys

data = sys.stdin.read().splitlines()
bad = []
for i, line in enumerate(data):
    if re.search(r"\bname:\s*AGENT_MODE\b", line):
        window = "\n".join(data[i:i+8])
        if re.search(r"\bvalue:\s*(LIVE|EXECUTE)\b", window, re.IGNORECASE):
            bad.append(window)
if bad:
    print("\n---\n".join(bad))
    sys.exit(2)
sys.exit(0)
PY
  then
    add_result "safety.agent_mode_not_execute" "PASS" "no AGENT_MODE=LIVE/EXECUTE detected"
  else
    add_result "safety.agent_mode_not_execute" "FAIL" "AGENT_MODE=LIVE/EXECUTE detected in workload env"
  fi

  # Kill switch exists and is ON (execution halted)
  KS="$(kubectl -n "${NS}" get configmap agenttrader-kill-switch -o jsonpath='{.data.EXECUTION_HALTED}' 2>/dev/null || true)"
  append_evidence "kill switch (ConfigMap agenttrader-kill-switch)" "${KS:-<missing>}"
  if [[ "${KS}" == "1" ]]; then
    add_result "safety.kill_switch" "PASS" "EXECUTION_HALTED=1"
  else
    add_result "safety.kill_switch" "FAIL" "EXECUTION_HALTED is not 1 (value=${KS:-missing})"
  fi

  # Stale-marketdata gating: marketdata /healthz must be OK (in-cluster)
  MARKETDATA_HEALTH=""
  set +e
  MARKETDATA_HEALTH="$(kubectl -n "${NS}" run readiness-curl --rm -i --restart=Never --image=curlimages/curl:8.5.0 -- \
    sh -lc 'curl -fsS --max-time 3 "http://marketdata-mcp-server/healthz" || exit 2' 2>&1)"
  MD_RC=$?
  set -e
  append_evidence "marketdata /healthz (in-cluster)" "${MARKETDATA_HEALTH}"
  if [[ "${MD_RC}" != "0" ]]; then
    add_result "safety.marketdata_fresh" "FAIL" "cannot validate marketdata freshness (healthz unreachable or non-200)"
  else
    if printf "%s" "${MARKETDATA_HEALTH}" | python3 - <<'PY'
import json,sys
s = sys.stdin.read()
try:
    obj = json.loads(s)
except Exception:
    sys.exit(2)
sys.exit(0 if obj.get("ok") is True else 3)
PY
    then
      add_result "safety.marketdata_fresh" "PASS" "marketdata healthz ok=true"
    else
      add_result "safety.marketdata_fresh" "FAIL" "marketdata healthz did not report ok=true"
    fi
  fi

  # Confirm no bypass env toggles are enabled
  if printf "%s" "${MANIFEST_YAML}" | python3 - <<'PY'
import re,sys
sys.exit(0 if re.search(r"(MARKETDATA_HEALTH_CHECK_DISABLED|MARKETDATA_FORCE_STALE)", sys.stdin.read()) else 2)
PY
  then
    if printf "%s" "${MANIFEST_YAML}" | python3 - <<'PY'
import re,sys
sys.exit(0 if re.search(r"MARKETDATA_HEALTH_CHECK_DISABLED[\s\S]{0,200}(1|true|yes|on)", sys.stdin.read(), re.IGNORECASE) else 2)
PY
    then
      add_result "safety.marketdata_bypass_disabled" "FAIL" "MARKETDATA_HEALTH_CHECK_DISABLED enabled"
    elif printf "%s" "${MANIFEST_YAML}" | python3 - <<'PY'
import re,sys
sys.exit(0 if re.search(r"MARKETDATA_FORCE_STALE[\s\S]{0,200}(1|true|yes|on)", sys.stdin.read(), re.IGNORECASE) else 2)
PY
    then
      add_result "safety.marketdata_bypass_disabled" "FAIL" "MARKETDATA_FORCE_STALE enabled"
    else
      add_result "safety.marketdata_bypass_disabled" "PASS" "no marketdata bypass toggles enabled"
    fi
  else
    add_result "safety.marketdata_bypass_disabled" "PASS" "no marketdata bypass toggles present"
  fi

  # Execution-agent disabled (scaled 0 or not present)
  EXEC_FOUND=0
  EXEC_BAD=0
  shopt -s nocasematch
  ALL_WORKLOADS="$(kubectl -n "${NS}" get deploy,sts -o jsonpath='{range .items[*]}{.kind}{":"}{.metadata.name}{"\t"}{.spec.replicas}{"\n"}{end}' 2>/dev/null || true)"
  while IFS=$'\t' read -r id reps; do
    [[ -z "${id}" ]] && continue
    if [[ "${id}" =~ (execution|executor|exec-?engine) ]]; then
      EXEC_FOUND=1
      reps="${reps:-0}"
      if [[ "${reps}" != "0" ]]; then
        EXEC_BAD=1
      fi
    fi
  done <<< "${ALL_WORKLOADS}"
  shopt -u nocasematch
  if [[ "${EXEC_FOUND}" == "0" ]]; then
    add_result "safety.execution_agents_disabled" "PASS" "no execution workloads detected in cluster"
  else
    if [[ "${EXEC_BAD}" == "1" ]]; then
      add_result "safety.execution_agents_disabled" "FAIL" "execution workload replicas > 0 detected"
    else
      add_result "safety.execution_agents_disabled" "PASS" "execution workloads present but scaled to 0"
    fi
  fi

  # Service discovery: v2 services should be ClusterIP unless explicitly documented
  SVC_TYPES="$(kubectl -n "${NS}" get svc -l app.kubernetes.io/part-of=agent-trader-v2 -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.type}{"\n"}{end}' 2>/dev/null || true)"
  append_evidence "services (type)" "${SVC_TYPES:-<none>}"
  BAD_SVC=0
  while IFS=$'\t' read -r svc typ; do
    [[ -z "${svc}" ]] && continue
    if [[ "${typ}" == "LoadBalancer" || "${typ}" == "NodePort" ]]; then
      BAD_SVC=1
    fi
  done <<< "${SVC_TYPES}"
  if [[ "${BAD_SVC}" == "1" ]]; then
    add_result "infra.service_discovery" "FAIL" "non-ClusterIP v2 service detected"
  else
    add_result "infra.service_discovery" "PASS" "v2 services are ClusterIP (or none discovered)"
  fi

  # Capacity / headroom (best-effort, fail-closed if metrics are unavailable)
  TOP_NODES=""
  TOP_PODS=""
  set +e
  TOP_NODES="$(kubectl top nodes 2>&1)"
  TOP_NODES_RC=$?
  TOP_PODS="$(kubectl -n "${NS}" top pods -l app.kubernetes.io/part-of=agent-trader-v2 2>&1)"
  TOP_PODS_RC=$?
  set -e
  append_evidence "capacity (kubectl top nodes)" "${TOP_NODES}"
  append_evidence "capacity (kubectl top pods)" "${TOP_PODS}"
  if [[ "${TOP_NODES_RC}" == "0" && "${TOP_PODS_RC}" == "0" ]]; then
    add_result "infra.capacity_headroom" "PASS" "metrics available (kubectl top succeeded)"
  else
    add_result "infra.capacity_headroom" "FAIL" "cannot validate headroom (kubectl top failed; metrics-server/RBAC may be missing)"
  fi

  # /ops/status calls (best-effort, in-cluster via pod IPs)
  POD_IPS="$(kubectl -n "${NS}" get pods -l app.kubernetes.io/part-of=agent-trader-v2 -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.podIP}{"\n"}{end}' 2>/dev/null || true)"
  append_evidence "pod IPs" "${POD_IPS:-<none>}"
  OPS_OUT=""
  OPS_RC=0
  if [[ -n "${POD_IPS}" ]]; then
    # Build a single shell script executed inside an ephemeral curl pod.
    CURL_SCRIPT="set -e; "
    while IFS=$'\t' read -r pname pip; do
      [[ -z "${pname}" || -z "${pip}" ]] && continue
      CURL_SCRIPT+="echo \"== ${pname} http://${pip}:8080/ops/status ==\"; "
      CURL_SCRIPT+="(curl -sS --max-time 3 -w \"\\nHTTP:%{http_code}\\n\" \"http://${pip}:8080/ops/status\" || true); "
    done <<< "${POD_IPS}"
    set +e
    OPS_OUT="$(kubectl -n "${NS}" run readiness-curl --rm -i --restart=Never --image=curlimages/curl:8.5.0 -- sh -lc "${CURL_SCRIPT}" 2>&1)"
    OPS_RC=$?
    set -e
  fi
  append_evidence "/ops/status sampling (pod IPs, in-cluster)" "${OPS_OUT:-<skipped>}"
  if [[ "${OPS_RC}" != "0" ]]; then
    add_result "health.ops_status" "FAIL" "/ops/status sampling failed"
  else
    if printf "%s" "${OPS_OUT}" | python3 - <<'PY'
import re,sys
codes = re.findall(r"HTTP:(\d{3})", sys.stdin.read())
if not codes:
    sys.exit(3)
bad = [c for c in codes if c != "200"]
sys.exit(0 if not bad else 2)
PY
    then
      add_result "health.ops_status" "PASS" "/ops/status reachable (all sampled endpoints 200)"
    else
      add_result "health.ops_status" "FAIL" "/ops/status not healthy (missing 200s or non-200 responses)"
    fi
  fi

  # Deploy report generator (auditable)
  if [[ -f "${ROOT_DIR}/scripts/report_v2_deploy.sh" ]]; then
    if run_and_capture "scripts/report_v2_deploy.sh --namespace ${NS}" bash "${ROOT_DIR}/scripts/report_v2_deploy.sh" --namespace "${NS}"; then
      add_result "health.deploy_report_generator" "PASS" "deploy report generated"
    else
      add_result "health.deploy_report_generator" "FAIL" "deploy report generator failed"
    fi
  else
    add_result "health.deploy_report_generator" "FAIL" "scripts/report_v2_deploy.sh missing"
  fi
fi

# -------------------------
# Write JSON + MD reports
# -------------------------

python3 - "${RESULTS_TSV}" "${REPORT_JSON}" "${NOW_UTC}" "${GIT_SHA}" "${GIT_BRANCH}" "${KUBE_CONTEXT}" "${NS}" "${READY}" <<'PY'
import json
import sys

tsv_path, out_path, now_utc, git_sha, git_branch, kube_context, ns, ready = sys.argv[1:]
ready_bool = (str(ready) == "1")

checks = []
with open(tsv_path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t", 2)
        while len(parts) < 3:
            parts.append("")
        name, status, details = parts[0], parts[1], parts[2]
        checks.append({"name": name, "status": status, "details": details})

payload = {
    "generated_utc": now_utc,
    "git_sha": git_sha,
    "git_branch": git_branch,
    "kubectl_context": kube_context,
    "namespace": ns,
    "ready": ready_bool,
    "checks": checks,
}

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2, sort_keys=True)
    f.write("\n")
PY

{
  cat <<EOF
## AgentTrader v2 — Readiness Report

- **Generated (UTC)**: ${NOW_UTC}
- **Git SHA**: \`${GIT_SHA}\`
- **Git branch**: \`${GIT_BRANCH}\`
- **kubectl context**: \`${KUBE_CONTEXT}\`
- **namespace**: \`${NS}\`

### Overall result: $( [[ "${READY}" == "1" ]] && echo "READY (GO)" || echo "NOT READY (NO-GO)" )

| Check | Status | Details |
| --- | --- | --- |
EOF

  while IFS=$'\t' read -r name status details; do
    [[ -z "${name}" ]] && continue
    printf "| %s | %s | %s |\n" "${name}" "${status}" "${details}"
  done < "${RESULTS_TSV}"

  cat <<EOF

## Evidence
EOF

  cat "${EVIDENCE_MD}"
} > "${REPORT_MD}"

echo "OK: wrote:"
echo " - ${REPORT_MD}"
echo " - ${REPORT_JSON}"

if [[ "${READY}" == "1" ]]; then
  exit 0
fi
exit 3

