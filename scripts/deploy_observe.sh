#!/usr/bin/env bash
set -euo pipefail

# One-command, deterministic, safe deploy:
# - requires TAG=<sha>
# - deploys ONLY safe workloads: marketdata-mcp-server + strategy-engine
# - waits for rollout + validates pinned images
# - prints final status summary
#
# Safety constraint: must not touch execution workloads.

TAG=""
NS="trading-floor"
TIMEOUT="5m"
CONTEXT=""

K8S_MARKETDATA="k8s/20-marketdata-mcp-server-deployment-and-service.yaml"
K8S_STRATEGY_ENGINE="k8s/25-strategy-engine-deployment-and-service.yaml"

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy_observe.sh --tag <sha> [options]

Required:
  --tag <sha>            Image tag to deploy (git SHA recommended)

Options:
  --namespace <ns>       Namespace to deploy into (default: trading-floor; must match manifests)
  --timeout <dur>        Rollout timeout (default: 5m)
  --context <ctx>        kubectl context (optional)
  -h, --help             Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG="${2:?}"; shift 2;;
    --namespace) NS="${2:?}"; shift 2;;
    --timeout) TIMEOUT="${2:?}"; shift 2;;
    --context) CONTEXT="${2:?}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "ERROR: unknown arg: $1" >&2; usage; exit 2;;
  esac
done

if [[ -z "${TAG}" ]]; then
  echo "ERROR: --tag is required (example: --tag \$(git rev-parse --short HEAD))" >&2
  exit 2
fi

if [[ ! "${TAG}" =~ ^[0-9a-fA-F]{7,40}$ ]]; then
  echo "ERROR: TAG must look like a git SHA (7-40 hex chars). Got: '${TAG}'" >&2
  exit 2
fi

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "ERROR: not inside a git repository (cannot resolve repo root)" >&2
  exit 1
fi
cd "${ROOT}"

for f in "${K8S_MARKETDATA}" "${K8S_STRATEGY_ENGINE}"; do
  if [[ ! -f "${f}" ]]; then
    echo "ERROR: missing required manifest: ${f}" >&2
    exit 2
  fi
done

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl not found in PATH" >&2
  exit 2
fi

kargs=()
if [[ -n "${CONTEXT}" ]]; then
  kargs+=(--context "${CONTEXT}")
fi

manifest_ns="$(
  python3 - <<'PY' "${K8S_MARKETDATA}" "${K8S_STRATEGY_ENGINE}"
import re
import sys

paths = sys.argv[1:]
ns = None
for p in paths:
    with open(p, "r", encoding="utf-8") as f:
        txt = f.read()
    # Prefer the first explicit metadata.namespace occurrence.
    m = re.search(r"(?m)^\s*namespace:\s*([A-Za-z0-9-]+)\s*$", txt)
    found = m.group(1) if m else ""
    if not found:
        print(f"ERROR: no metadata.namespace found in {p}", file=sys.stderr)
        sys.exit(2)
    if ns is None:
        ns = found
    elif found != ns:
        print(f"ERROR: namespace mismatch across manifests: {ns} vs {found} ({p})", file=sys.stderr)
        sys.exit(2)
print(ns)
PY
)"

if [[ -z "${manifest_ns}" ]]; then
  echo "ERROR: unable to determine manifest namespace" >&2
  exit 2
fi

if [[ "${NS}" != "${manifest_ns}" ]]; then
  echo "ERROR: --namespace '${NS}' does not match manifest namespace '${manifest_ns}'" >&2
  echo "Refusing to deploy to avoid unexpected namespace behavior." >&2
  exit 2
fi

echo "== deploy-observe =="
echo "tag:       ${TAG}"
echo "namespace: ${NS}"
if [[ -n "${CONTEXT}" ]]; then echo "context:   ${CONTEXT}"; fi
echo ""

echo "== kubectl apply (safe workloads only) =="
kubectl "${kargs[@]}" apply -f "${K8S_MARKETDATA}" -f "${K8S_STRATEGY_ENGINE}"

compute_tagged_image() {
  # Usage: compute_tagged_image <image_ref> <tag>
  python3 - <<'PY' "$1" "$2"
import sys

img = sys.argv[1].strip()
tag = sys.argv[2].strip()

if "@" in img:
    base = img.split("@", 1)[0]
else:
    # Remove existing tag, but only if it's after the last '/'.
    last_slash = base_slash = img.rfind("/")
    after = img[last_slash + 1 :]
    if ":" in after:
        base = img.rsplit(":", 1)[0]
    else:
        base = img
print(f"{base}:{tag}")
PY
}

marketdata_img="$(
  python3 - <<'PY' "${K8S_MARKETDATA}"
import re, sys
p = sys.argv[1]
with open(p, "r", encoding="utf-8") as f:
    txt = f.read()
m = re.search(r"(?m)^\s*image:\s*(\S+)\s*$", txt)
print(m.group(1) if m else "")
PY
)"

strategy_img="$(
  python3 - <<'PY' "${K8S_STRATEGY_ENGINE}"
import re, sys
p = sys.argv[1]
with open(p, "r", encoding="utf-8") as f:
    txt = f.read()
m = re.search(r"(?m)^\s*image:\s*(\S+)\s*$", txt)
print(m.group(1) if m else "")
PY
)"

if [[ -z "${marketdata_img}" || -z "${strategy_img}" ]]; then
  echo "ERROR: unable to extract images from manifests" >&2
  exit 2
fi

marketdata_new_img="$(compute_tagged_image "${marketdata_img}" "${TAG}")"
strategy_new_img="$(compute_tagged_image "${strategy_img}" "${TAG}")"

echo ""
echo "== pin images to tag ${TAG} (safe workloads only) =="
echo "marketdata-mcp-server: ${marketdata_new_img}"
kubectl "${kargs[@]}" -n "${NS}" set image deploy/marketdata-mcp-server \
  marketdata-mcp-server-container="${marketdata_new_img}"
echo "strategy-engine:      ${strategy_new_img}"
kubectl "${kargs[@]}" -n "${NS}" set image deploy/strategy-engine \
  strategy-engine="${strategy_new_img}"

echo ""
bash ./scripts/rollout_guard.sh \
  --namespace "${NS}" \
  --resource "deploy/marketdata-mcp-server" \
  --container "marketdata-mcp-server-container" \
  --tag "${TAG}" \
  --timeout "${TIMEOUT}" \
  $( [[ -n "${CONTEXT}" ]] && printf '%s' "--context ${CONTEXT}" )

bash ./scripts/rollout_guard.sh \
  --namespace "${NS}" \
  --resource "deploy/strategy-engine" \
  --container "strategy-engine" \
  --tag "${TAG}" \
  --timeout "${TIMEOUT}" \
  $( [[ -n "${CONTEXT}" ]] && printf '%s' "--context ${CONTEXT}" )

echo ""
echo "== final status summary (safe workloads only) =="
kubectl "${kargs[@]}" -n "${NS}" get deploy marketdata-mcp-server strategy-engine -o wide
echo ""
kubectl "${kargs[@]}" -n "${NS}" get pods -l app=marketdata-mcp-server -o wide || true
kubectl "${kargs[@]}" -n "${NS}" get pods -l app=strategy-engine -o wide || true

echo ""
echo "OK: deploy-observe complete (tag=${TAG})"

