#!/usr/bin/env bash
#
# Validate Kubernetes YAML manifests with kubectl client dry-run.
#
# This is intended as a merge-safety gate: it fails if any manifest cannot be
# parsed/applied by kubectl (client-side).

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: validate_k8s_yaml.sh [--k8s-dir <dir>] [--help]

Options:
  --k8s-dir <dir>  Directory containing Kubernetes manifests (default: k8s)
  --help           Show this help text

Environment:
  K8S_DIR          Alternative way to set --k8s-dir
EOF
}

K8S_DIR="${K8S_DIR:-k8s}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --k8s-dir)
      K8S_DIR="${2:-}"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl not found on PATH" >&2
  exit 2
fi

if [[ ! -d "$K8S_DIR" ]]; then
  echo "INFO: no '$K8S_DIR' directory found; nothing to validate"
  exit 0
fi

shopt -s nullglob globstar
files=( "$K8S_DIR"/**/*.yaml "$K8S_DIR"/**/*.yml )

if [[ ${#files[@]} -eq 0 ]]; then
  echo "INFO: no manifests found under '$K8S_DIR' (*.yaml, *.yml)"
  exit 0
fi

echo "== k8s yaml validate =="
echo "Repo root: $ROOT"
echo "K8S_DIR:   $K8S_DIR"
echo "Files:     ${#files[@]}"
echo ""

ok=0
fail=0

for f in "${files[@]}"; do
  [[ -f "$f" ]] || continue
  echo "-> kubectl apply --dry-run=client -f $f"
  if kubectl apply --dry-run=client -f "$f" >/dev/null; then
    ok=$((ok + 1))
  else
    fail=$((fail + 1))
  fi
done

echo ""
echo "Result: ok=$ok fail=$fail"

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
