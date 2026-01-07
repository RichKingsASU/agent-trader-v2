#!/usr/bin/env bash
set -euo pipefail

# Rollout guard for a single Kubernetes Deployment.
#
# Responsibilities:
# - Verify the Deployment's container image tag/digest matches an expected value
# - Watch rollout status with a timeout
# - If any pods enter CrashLoopBackOff, print log tail(s) and exit non-zero
# - Print a final summary

export KUBECTL_PAGER=""
export PAGER=cat

NS="${NAMESPACE:-default}"
CTX=""
DEPLOY=""
EXPECTED_TAG=""
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-300}"
POLL_SECONDS="${POLL_SECONDS:-5}"
TAIL_LINES="${TAIL_LINES:-200}"
SINCE_WINDOW="${SINCE_WINDOW:-30m}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/rollout_guard.sh --namespace <ns> --deployment <name> --tag <expected> [--timeout <seconds>] [--context <ctx>]

Env (optional):
  TIMEOUT_SECONDS  Default timeout (seconds), default: 300
  POLL_SECONDS     Polling interval (seconds), default: 5
  TAIL_LINES       Log tail lines on CrashLoopBackOff, default: 200
  SINCE_WINDOW     Log lookback window, default: 30m

Examples:
  ./scripts/rollout_guard.sh --namespace trading-floor --deployment strategy-engine --tag 54afffe
  TIMEOUT_SECONDS=600 ./scripts/rollout_guard.sh -n trading-floor -d execution-engine --tag 54afffe --context gke_proj_region_cluster
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace|-n) NS="${2:?}"; shift 2;;
    --context) CTX="${2:?}"; shift 2;;
    --deployment|-d) DEPLOY="${2:?}"; shift 2;;
    --tag) EXPECTED_TAG="${2:?}"; shift 2;;
    --timeout) TIMEOUT_SECONDS="${2:?}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "ERROR: unknown arg: $1" >&2; usage; exit 2;;
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

if [[ -z "${DEPLOY}" ]]; then
  echo "ERROR: --deployment is required" >&2
  exit 2
fi
if [[ -z "${EXPECTED_TAG}" ]]; then
  echo "ERROR: --tag is required" >&2
  exit 2
fi

require_cmd kubectl
require_cmd python3

kargs=()
if [[ -n "${CTX}" ]]; then
  kargs+=(--context "${CTX}")
fi

set +e
kubectl "${kargs[@]}" get namespace "${NS}" >/dev/null 2>&1
ns_ok=$?
set -e
if [[ "${ns_ok}" != "0" ]]; then
  echo "ERROR: cluster unreachable or namespace '${NS}' not found." >&2
  echo "HINT: verify context (kubectl config get-contexts) and namespace (kubectl get ns)." >&2
  exit 1
fi

if ! kubectl "${kargs[@]}" -n "${NS}" get deploy "${DEPLOY}" >/dev/null 2>&1; then
  echo "ERROR: deployment '${DEPLOY}' not found in namespace '${NS}'" >&2
  echo "HINT: run: kubectl ${CTX:+--context ${CTX}} -n ${NS} get deploy" >&2
  exit 1
fi

DEP_JSON="$(kubectl "${kargs[@]}" -n "${NS}" get deploy "${DEPLOY}" -o json)"

SELECTOR="$(printf "%s" "${DEP_JSON}" | python3 - <<'PY'
import json,sys
obj = json.loads(sys.stdin.read())
labels = obj.get("spec", {}).get("selector", {}).get("matchLabels", {}) or {}
if not isinstance(labels, dict) or not labels:
    print("")
    raise SystemExit(0)
parts = []
for k in sorted(labels.keys()):
    v = labels[k]
    if v is None:
        continue
    parts.append(f"{k}={v}")
print(",".join(parts))
PY
)"

declare -a IMG_LINES=()
while IFS= read -r line; do
  [[ -z "${line}" ]] && continue
  IMG_LINES+=("${line}")
done < <(kubectl "${kargs[@]}" -n "${NS}" get deploy "${DEPLOY}" -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{"\t"}{.image}{"\n"}{end}')

if [[ "${#IMG_LINES[@]}" -eq 0 ]]; then
  echo "ERROR: could not read container images from deploy/${DEPLOY} (namespace=${NS})" >&2
  exit 1
fi

extract_ref_tail() {
  # Input: full image reference. Output: tag or digest tail.
  # - repo/image:tag     => tag
  # - repo/image@sha256: => sha256:...
  local img="$1"
  if [[ "${img}" == *@* ]]; then
    printf "%s" "${img##*@}"
    return 0
  fi
  if [[ "${img}" == *:* ]]; then
    printf "%s" "${img##*:}"
    return 0
  fi
  printf "%s" ""
}

IMAGE_MISMATCH=0
IMAGE_REPORT=""
for entry in "${IMG_LINES[@]}"; do
  cname="${entry%%$'\t'*}"
  cimg="${entry#*$'\t'}"
  ref_tail="$(extract_ref_tail "${cimg}")"
  IMAGE_REPORT+="- ${cname}: ${cimg} (ref=${ref_tail:-<none>})"$'\n'
  if [[ -z "${ref_tail}" || "${ref_tail}" != "${EXPECTED_TAG}" ]]; then
    IMAGE_MISMATCH=1
  fi
done

STATUS="UNKNOWN"
FAIL_REASON=""
START_EPOCH="$(date +%s)"

print_summary() {
  local end_epoch elapsed
  end_epoch="$(date +%s)"
  elapsed="$((end_epoch - START_EPOCH))"

  echo ""
  echo "== rollout guard summary =="
  echo "status:     ${STATUS}"
  [[ -n "${FAIL_REASON}" ]] && echo "reason:     ${FAIL_REASON}"
  echo "namespace:  ${NS}"
  echo "deployment: ${DEPLOY}"
  echo "expected:   ${EXPECTED_TAG}"
  echo "context:    $(kubectl "${kargs[@]}" config current-context 2>/dev/null || echo "UNKNOWN")"
  echo "selector:   ${SELECTOR:-<unknown>}"
  echo "elapsed:    ${elapsed}s"
  echo ""
  echo "images:"
  printf "%s" "${IMAGE_REPORT}"
  echo ""
  if [[ -n "${SELECTOR}" ]]; then
    echo "pods:"
    kubectl "${kargs[@]}" -n "${NS}" get pods -l "${SELECTOR}" -o wide 2>/dev/null || true
  fi
  echo ""
}

if [[ "${IMAGE_MISMATCH}" == "1" ]]; then
  STATUS="FAIL"
  FAIL_REASON="deployment image tag/digest does not match expected (${EXPECTED_TAG})"
  print_summary
  exit 1
fi

detect_crashloop() {
  # Prints tab-separated: pod\tcontainer\treason
  local pods_json="$1"
  python3 - <<'PY' "${pods_json}"
import json,sys
pods = json.loads(sys.argv[1])
items = pods.get("items", []) or []
for p in items:
    name = p.get("metadata", {}).get("name", "")
    statuses = (p.get("status", {}) or {}).get("containerStatuses", []) or []
    for cs in statuses:
        st = cs.get("state", {}) or {}
        waiting = st.get("waiting") or {}
        reason = waiting.get("reason") or ""
        if reason == "CrashLoopBackOff":
            print(f"{name}\t{cs.get('name','')}\t{reason}")
PY
}

DEADLINE="$((START_EPOCH + TIMEOUT_SECONDS))"
LAST_ROLLOUT_OUT=""

while true; do
  now="$(date +%s)"
  if [[ "${now}" -ge "${DEADLINE}" ]]; then
    STATUS="FAIL"
    FAIL_REASON="rollout timed out after ${TIMEOUT_SECONDS}s"
    break
  fi

  if [[ -n "${SELECTOR}" ]]; then
    set +e
    PODS_JSON="$(kubectl "${kargs[@]}" -n "${NS}" get pods -l "${SELECTOR}" -o json 2>/dev/null)"
    pods_rc=$?
    set -e
    if [[ "${pods_rc}" == "0" && -n "${PODS_JSON}" ]]; then
      CRASH_LINES="$(detect_crashloop "${PODS_JSON}")"
      if [[ -n "${CRASH_LINES}" ]]; then
        STATUS="FAIL"
        FAIL_REASON="CrashLoopBackOff detected"
        echo "ERROR: CrashLoopBackOff detected in namespace '${NS}' for deploy/${DEPLOY}." >&2
        echo "" >&2
        while IFS=$'\t' read -r pod container reason; do
          [[ -z "${pod}" ]] && continue
          echo "== logs: pod/${pod} container=${container} reason=${reason} (current) ==" >&2
          kubectl "${kargs[@]}" -n "${NS}" logs "${pod}" -c "${container}" --tail="${TAIL_LINES}" --since="${SINCE_WINDOW}" --timestamps 2>&1 || true
          echo "" >&2
          echo "== logs: pod/${pod} container=${container} reason=${reason} (previous) ==" >&2
          kubectl "${kargs[@]}" -n "${NS}" logs "${pod}" -c "${container}" --previous --tail="${TAIL_LINES}" --since="${SINCE_WINDOW}" --timestamps 2>&1 || true
          echo "" >&2
        done <<< "${CRASH_LINES}"
        print_summary
        exit 1
      fi
    fi
  fi

  set +e
  LAST_ROLLOUT_OUT="$(kubectl "${kargs[@]}" -n "${NS}" rollout status "deploy/${DEPLOY}" --timeout=1s 2>&1)"
  rc=$?
  set -e
  if [[ "${rc}" == "0" ]]; then
    STATUS="OK"
    break
  fi

  sleep "${POLL_SECONDS}"
done

if [[ "${STATUS}" != "OK" ]]; then
  echo "ERROR: rollout did not complete successfully." >&2
  [[ -n "${LAST_ROLLOUT_OUT}" ]] && echo "${LAST_ROLLOUT_OUT}" >&2
  print_summary
  exit 1
fi

print_summary
exit 0

