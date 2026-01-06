#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
K8S_DIR="${REPO_ROOT}/deploy/k8s"

echo "Running structure and no-gcr guards..."
bash "${REPO_ROOT}/scripts/guard_structure.sh"
bash "${REPO_ROOT}/scripts/guard_no_gcr.sh"

kubectl apply -k "${K8S_DIR}"
