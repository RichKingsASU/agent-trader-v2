#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
K8S_DIR="${1:-k8s}"

cd "$ROOT_DIR"

if [[ ! -d "$K8S_DIR" ]]; then
  echo "ERROR: Kubernetes manifest directory not found: $K8S_DIR" >&2
  exit 2
fi

if command -v rg >/dev/null 2>&1; then
  SEARCH_BIN="rg"
else
  SEARCH_BIN="grep"
fi

fail=0

note() { echo "[ci_safety_lint] $*"; }
err() { echo "[ci_safety_lint][ERROR] $*" >&2; }

list_k8s_files() {
  if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if [[ "$SEARCH_BIN" == "rg" ]]; then
      git ls-files "$K8S_DIR" | { rg --no-heading '\.ya?ml$' 2>/dev/null || true; }
    else
      git ls-files "$K8S_DIR" | { grep -E '\.ya?ml$' 2>/dev/null || true; }
    fi
  else
    find "$K8S_DIR" -type f \( -name '*.yaml' -o -name '*.yml' \) | sort
  fi
}

search_with_lines() {
  # Usage: search_with_lines <pattern> <path>
  local pattern="$1"
  local path="$2"
  if [[ "$SEARCH_BIN" == "rg" ]]; then
    rg -n --no-heading "$pattern" "$path" 2>/dev/null || true
  else
    grep -n -E "$pattern" "$path" 2>/dev/null || true
  fi
}

has_match() {
  # Usage: has_match <pattern> <file>
  local pattern="$1"
  local file="$2"
  if [[ "$SEARCH_BIN" == "rg" ]]; then
    rg -q "$pattern" "$file" 2>/dev/null
  else
    grep -q -E "$pattern" "$file" 2>/dev/null
  fi
}

kind_line() {
  # Print the line number of the first "kind:" line (or 1).
  local file="$1"
  local ln
  ln="$(awk '/^[[:space:]]*kind:[[:space:]]*/ { print NR; exit }' "$file" 2>/dev/null || true)"
  echo "${ln:-1}"
}

note "Scanning manifests in: $K8S_DIR"

# Global forbidden patterns (all manifests)
note "Checking forbidden image tags (:latest)"
latest_hits="$(search_with_lines ':latest\\b' "$K8S_DIR")"
if [[ -n "$latest_hits" ]]; then
  err "Found forbidden ':latest' tag(s):"
  echo "$latest_hits" >&2
  fail=1
fi

note "Checking forbidden AGENT_MODE=EXECUTE"
# Direct (inline) form
execute_inline_hits="$(search_with_lines 'AGENT_MODE[[:space:]]*=[[:space:]]*EXECUTE\\b' "$K8S_DIR")"
if [[ -n "$execute_inline_hits" ]]; then
  err "Found forbidden 'AGENT_MODE=EXECUTE' string(s):"
  echo "$execute_inline_hits" >&2
  fail=1
fi
# YAML env form: name: AGENT_MODE ... value: EXECUTE (best-effort, multiline)
if [[ "$SEARCH_BIN" == "rg" ]]; then
  execute_yaml_hits="$(rg -n --no-heading --multiline --multiline-dotall 'name:[[:space:]]*AGENT_MODE[\\s\\S]{0,200}value:[[:space:]]*EXECUTE\\b' "$K8S_DIR" 2>/dev/null || true)"
  if [[ -n "$execute_yaml_hits" ]]; then
    err "Found forbidden AGENT_MODE value EXECUTE in YAML env blocks:"
    echo "$execute_yaml_hits" >&2
    fail=1
  fi
fi

# Per-workload enforcement
required_label_re='app\\.kubernetes\\.io/part-of:[[:space:]]*agent-trader-v2\\b'
required_env_vars=(REPO_ID AGENT_NAME AGENT_ROLE AGENT_MODE)

note "Checking workload manifests for required labels/env vars"
while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  [[ ! -f "$file" ]] && continue

  # Only enforce on workload kinds (avoid forcing env vars on Namespace/Service/ConfigMap, etc.)
  if ! has_match '^[[:space:]]*kind:[[:space:]]*(Deployment|StatefulSet|DaemonSet|Job|CronJob)\\b' "$file"; then
    continue
  fi

  anchor_ln="$(kind_line "$file")"

  if ! has_match "$required_label_re" "$file"; then
    err "${file}:${anchor_ln}: missing required label 'app.kubernetes.io/part-of: agent-trader-v2'"
    fail=1
  fi

  for v in "${required_env_vars[@]}"; do
    if ! has_match "name:[[:space:]]*$v\\b" "$file"; then
      err "${file}:${anchor_ln}: missing required env var '$v' (must appear as 'name: $v')"
      fail=1
    fi
  done
done < <(list_k8s_files)

if [[ "$fail" -ne 0 ]]; then
  err "Safety lint FAILED."
  exit 1
fi

note "Safety lint OK."
