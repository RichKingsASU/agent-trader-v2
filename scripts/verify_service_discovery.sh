#!/usr/bin/env bash
set -euo pipefail

NS="${NS:-trading-floor}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

pass=0
fail=0

echo "== Applying base k8s manifests (non-recursive) =="
kubectl apply -f "${ROOT}/k8s/" >/dev/null
echo "ok"
echo ""

_check() {
  local name="$1"
  local url="$2"

  echo -n "CHECK ${name}: ${url} ... "
  if kubectl -n "${NS}" run "tmp-curl-$RANDOM" \
      --rm -i --restart=Never \
      --image=curlimages/curl \
      --command -- sh -lc "curl -fsS --max-time 5 '${url}' >/dev/null" >/dev/null 2>&1; then
    echo "PASS"
    pass=$((pass + 1))
  else
    echo "FAIL"
    fail=$((fail + 1))
  fi
}

_check "marketdata-mcp-server healthz" "http://agenttrader-marketdata-mcp-server/healthz"
_check "strategy-engine healthz" "http://agenttrader-strategy-engine/healthz"

echo ""
echo "RESULT: pass=${pass} fail=${fail}"

if [[ "${fail}" -gt 0 ]]; then
  exit 1
fi

