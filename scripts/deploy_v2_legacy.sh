#!/usr/bin/env bash
set -euo pipefail

# Legacy deploy script preserved for reference.
# Prefer: ./scripts/deploy_v2.sh (runs predeploy guardrails + deterministic rollout).

REQUIRED_REPO_ID="${REQUIRED_REPO_ID:-agent-trader-v2}"
REQUIRED_REMOTE_SUBSTR="${REQUIRED_REMOTE_SUBSTR:-RichKingsASU/agent-trader-v2}"

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "ERROR: Not inside a git repository. Refusing to deploy."
  exit 1
fi

cd "${ROOT}"

if [[ ! -f ".repo_id" ]]; then
  echo "ERROR: Missing .repo_id at repo root. Refusing to deploy."
  echo "Fix: create .repo_id containing exactly: ${REQUIRED_REPO_ID}"
  exit 1
fi

REPO_ID="$(tr -d ' \n\r\t' < .repo_id)"
if [[ "${REPO_ID}" != "${REQUIRED_REPO_ID}" ]]; then
  echo "ERROR: .repo_id mismatch. Expected '${REQUIRED_REPO_ID}', got '${REPO_ID}'. Refusing."
  exit 1
fi

ORIGIN_URL="$(git remote get-url origin 2>/dev/null || true)"
if [[ "${ORIGIN_URL}" != *"${REQUIRED_REMOTE_SUBSTR}"* ]]; then
  echo "ERROR: origin remote is not ${REQUIRED_REMOTE_SUBSTR}. Refusing."
  echo "origin: ${ORIGIN_URL}"
  exit 1
fi

if [[ "${ALLOW_DIRTY_DEPLOY:-0}" != "1" ]] && [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: Working tree is dirty. Commit or stash first. Refusing."
  echo ""
  git status --porcelain
  exit 1
fi

REF="${REF:-HEAD}"
SHA="$(git rev-parse --short "${REF}")"

PROJECT="${PROJECT:-agenttrader-prod}"
REGION="${REGION:-us-east4}"
REPO="${REPO:-trader-repo}"
NS="${NS:-trading-floor}"

echo "== Deploying AgentTrader v2 (legacy) =="
echo "repo_root: ${ROOT}"
echo "repo_id:   ${REPO_ID}"
echo "origin:    ${ORIGIN_URL}"
echo "project:   ${PROJECT}"
echo "region:    ${REGION}"
echo "repo:      ${REPO}"
echo "namespace: ${NS}"
echo "ref:       ${REF}"
echo "sha:       ${SHA}"
echo ""

for bin in git gcloud kubectl; do
  if ! command -v "${bin}" >/dev/null 2>&1; then
    echo "ERROR: Missing required binary '${bin}' in PATH. Refusing."
    exit 1
  fi
done

if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
  echo "ERROR: No active gcloud account. Run: gcloud auth login"
  exit 1
fi

for cfg in cloudbuild.mcp.yaml cloudbuild.strategy-runtime.yaml cloudbuild.strategy-engine.yaml; do
  if [[ ! -f "${cfg}" ]]; then
    echo "ERROR: Missing required Cloud Build config: ${cfg}. Refusing."
    exit 1
  fi
done

echo "== Cloud Build: marketdata-mcp-server =="
gcloud builds submit --config cloudbuild.mcp.yaml .

echo "== Cloud Build: strategy-runtime =="
gcloud builds submit --config cloudbuild.strategy-runtime.yaml .

echo "== Cloud Build: strategy-engine =="
gcloud builds submit --config cloudbuild.strategy-engine.yaml .

echo "== kubectl apply k8s/ =="
kubectl apply -f k8s/

echo "== Pin images to SHA ${SHA} =="

if kubectl -n "${NS}" get deploy marketdata-mcp-server >/dev/null 2>&1; then
  kubectl -n "${NS}" set image deploy/marketdata-mcp-server \
    marketdata-mcp-server-container="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/marketdata-mcp-server:${SHA}"
fi

if kubectl -n "${NS}" get deploy strategy-engine >/dev/null 2>&1; then
  kubectl -n "${NS}" set image deploy/strategy-engine \
    strategy-engine="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/strategy-engine:${SHA}"
fi

if kubectl -n "${NS}" get statefulset gamma-strategy >/dev/null 2>&1; then
  kubectl -n "${NS}" set image statefulset/gamma-strategy \
    gamma-strategy-container="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/strategy-runtime:${SHA}"
fi

if kubectl -n "${NS}" get statefulset whale-strategy >/dev/null 2>&1; then
  kubectl -n "${NS}" set image statefulset/whale-strategy \
    whale-strategy-container="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/strategy-runtime:${SHA}"
fi

echo "== Rollout status =="
kubectl -n "${NS}" rollout status deploy/marketdata-mcp-server --timeout=300s || true
kubectl -n "${NS}" rollout status deploy/strategy-engine --timeout=300s || true
kubectl -n "${NS}" rollout status statefulset/gamma-strategy --timeout=300s || true
kubectl -n "${NS}" rollout status statefulset/whale-strategy --timeout=300s || true

echo ""
echo "Deploy script finished."

