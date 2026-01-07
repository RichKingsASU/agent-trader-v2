#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-trading-floor}"

echo "[ops] Applying PodMonitoring resources to namespace=${NAMESPACE}"

kubectl -n "${NAMESPACE}" apply -f ops/monitoring/gmp/podmonitoring-marketdata.yaml
kubectl -n "${NAMESPACE}" apply -f ops/monitoring/gmp/podmonitoring-strategy-gamma.yaml
kubectl -n "${NAMESPACE}" apply -f ops/monitoring/gmp/podmonitoring-strategy-whale.yaml

echo "[ops] Done."

