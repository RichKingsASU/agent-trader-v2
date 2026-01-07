#!/usr/bin/env bash
set -euo pipefail

# rollout_guard: fail-closed rollout wait + post-rollout assertions.
#
# This script is intentionally strict and deterministic.

NS="trading-floor"
RESOURCE=""
CONTAINER=""
TAG=""
TIMEOUT="5m"
CONTEXT=""

usage() {
  cat <<'EOF'
Usage: ./scripts/rollout_guard.sh --resource <kind/name> --container <containerName> --tag <sha> [options]

Required:
  --resource <kind/name>     Kubernetes resource to watch (e.g. deploy/strategy-engine)
  --container <name>         Container name within the workload to validate
  --tag <sha>                Expected image tag (e.g. git SHA)

Options:
  --namespace <ns>           Namespace (default: trading-floor)
  --timeout <dur>            Rollout timeout (default: 5m)
  --context <ctx>            kubectl context (optional)
  -h, --help                 Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NS="${2:?}"; shift 2;;
    --resource) RESOURCE="${2:?}"; shift 2;;
    --container) CONTAINER="${2:?}"; shift 2;;
    --tag) TAG="${2:?}"; shift 2;;
    --timeout) TIMEOUT="${2:?}"; shift 2;;
    --context) CONTEXT="${2:?}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "ERROR: unknown arg: $1" >&2; usage; exit 2;;
  esac
done

if [[ -z "${RESOURCE}" || -z "${CONTAINER}" || -z "${TAG}" ]]; then
  echo "ERROR: --resource, --container, and --tag are required" >&2
  usage
  exit 2
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl not found in PATH" >&2
  exit 2
fi

kargs=()
if [[ -n "${CONTEXT}" ]]; then
  kargs+=(--context "${CONTEXT}")
fi

echo ""
echo "== rollout_guard: ${RESOURCE} (ns=${NS}, timeout=${TIMEOUT}) =="

kubectl "${kargs[@]}" -n "${NS}" rollout status "${RESOURCE}" --timeout="${TIMEOUT}"

# Validate the expected image tag is present for the target container.
img="$(
  kubectl "${kargs[@]}" -n "${NS}" get "${RESOURCE}" \
    -o "jsonpath={.spec.template.spec.containers[?(@.name==\"${CONTAINER}\")].image}" 2>/dev/null || true
)"
if [[ -z "${img}" ]]; then
  echo "ERROR: unable to read container image for ${RESOURCE} container=${CONTAINER}" >&2
  exit 1
fi
if [[ "${img}" != *":${TAG}" ]]; then
  echo "ERROR: image tag mismatch for ${RESOURCE} container=${CONTAINER}" >&2
  echo "  expected suffix: :${TAG}" >&2
  echo "  actual image:    ${img}" >&2
  exit 1
fi

# Validate replicas are ready (deployment-focused; works safely for most workloads).
spec_repl="$(kubectl "${kargs[@]}" -n "${NS}" get "${RESOURCE}" -o "jsonpath={.spec.replicas}" 2>/dev/null || echo "")"
ready_repl="$(kubectl "${kargs[@]}" -n "${NS}" get "${RESOURCE}" -o "jsonpath={.status.readyReplicas}" 2>/dev/null || echo "")"
spec_repl="${spec_repl:-0}"
ready_repl="${ready_repl:-0}"

if [[ "${ready_repl}" != "${spec_repl}" ]]; then
  echo "ERROR: replica readiness mismatch for ${RESOURCE}" >&2
  echo "  spec.replicas:        ${spec_repl}" >&2
  echo "  status.readyReplicas: ${ready_repl}" >&2
  exit 1
fi

echo "OK: ${RESOURCE} rolled out; image=${img}; ready=${ready_repl}/${spec_repl}"

