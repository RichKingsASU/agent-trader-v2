#!/usr/bin/env bash
set -euo pipefail

# AgentTrader v2 — Pre-deploy guardrails (fail-fast).
#
# Refuses to deploy when:
# - kubectl context is not the expected cluster
# - required repo label missing or mismatched
# - any workload sets AGENT_MODE=EXECUTE
# - any k8s manifest image uses :latest, :dev, or an empty tag
# - any referenced image cannot be validated to exist (unless --allow-unknown-images)

NS="default"
K8S_DIR="k8s/"
PROJECT=""
EXPECTED_CONTEXT="${EXPECTED_KUBECTL_CONTEXT:-}"
ALLOW_UNKNOWN_IMAGES="0"

usage() {
  cat <<'EOF'
Usage: ./scripts/predeploy_guard.sh [options]

Options:
  --namespace <ns>            Kubernetes namespace (default: "default")
  --k8s-dir <dir>             Manifests directory (default: "k8s/")
  --project <gcp-project-id>   Optional GCP project id (used for image existence checks)
  --expected-context <ctx>     Expected kubectl context. If omitted, infer from gcloud config when possible.
  --allow-unknown-images       Allow images that cannot be validated (FAIL-SAFE is default)
  -h, --help                   Show help

Notes:
  - Strict rule: no ":latest" anywhere in k8s manifests.
  - This guard is intentionally conservative; unknown/templated images fail unless allowed.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NS="${2:?}"; shift 2;;
    --k8s-dir) K8S_DIR="${2:?}"; shift 2;;
    --project) PROJECT="${2:?}"; shift 2;;
    --expected-context) EXPECTED_CONTEXT="${2:?}"; shift 2;;
    --allow-unknown-images) ALLOW_UNKNOWN_IMAGES="1"; shift 1;;
    -h|--help) usage; exit 0;;
    *) echo "ERROR: Unknown arg: $1" >&2; usage; exit 2;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "FAIL predeploy_guard: not inside a git repository"
  exit 1
fi
cd "${ROOT}"

failures=()
warnings=()

need_bin() {
  local b="$1"
  if ! command -v "${b}" >/dev/null 2>&1; then
    failures+=("missing_binary: ${b}")
    return 1
  fi
  return 0
}

need_bin kubectl || true
need_bin python3 || true

if [[ ! -d "${K8S_DIR}" ]]; then
  failures+=("missing_k8s_dir: ${K8S_DIR}")
fi

current_ctx="$(kubectl config current-context 2>/dev/null || true)"
if [[ -z "${current_ctx}" ]]; then
  failures+=("kubectl_context: unable to determine current context")
fi

infer_expected_context() {
  if [[ -n "${EXPECTED_CONTEXT}" ]]; then
    return 0
  fi
  if ! command -v gcloud >/dev/null 2>&1; then
    return 0
  fi
  local p c loc
  p="$(gcloud config get-value project 2>/dev/null || true)"
  c="$(gcloud config get-value container/cluster 2>/dev/null || true)"
  loc="$(gcloud config get-value container/location 2>/dev/null || true)"
  if [[ -z "${loc}" ]]; then
    loc="$(gcloud config get-value container/zone 2>/dev/null || true)"
  fi
  if [[ -z "${loc}" ]]; then
    loc="$(gcloud config get-value container/region 2>/dev/null || true)"
  fi
  p="$(echo "${p}" | tr -d '[:space:]')"
  c="$(echo "${c}" | tr -d '[:space:]')"
  loc="$(echo "${loc}" | tr -d '[:space:]')"
  if [[ -n "${p}" && -n "${c}" && -n "${loc}" ]]; then
    EXPECTED_CONTEXT="gke_${p}_${loc}_${c}"
  fi
}

infer_expected_context

if [[ -z "${EXPECTED_CONTEXT}" ]]; then
  failures+=("kubectl_context: expected context not provided and could not infer from gcloud (set --expected-context or EXPECTED_KUBECTL_CONTEXT)")
else
  if [[ -n "${current_ctx}" && "${current_ctx}" != "${EXPECTED_CONTEXT}" ]]; then
    failures+=("kubectl_context_mismatch: current='${current_ctx}' expected='${EXPECTED_CONTEXT}'")
  fi
fi

manifest_files=()
if [[ -d "${K8S_DIR}" ]]; then
  # Deterministic order.
  while IFS= read -r f; do
    [[ -z "${f}" ]] && continue
    manifest_files+=("${f}")
  done < <(find "${K8S_DIR}" -type f \( -name '*.yaml' -o -name '*.yml' \) -print | LC_ALL=C sort)
fi

if [[ "${#manifest_files[@]}" -eq 0 ]]; then
  failures+=("no_manifests_found: ${K8S_DIR}")
fi

scan_out=""
if [[ "${#manifest_files[@]}" -gt 0 ]]; then
  scan_out="$(python3 - <<'PY' "${manifest_files[@]}" || true
import re
import sys

files = sys.argv[1:]
required_repo_id = "agent-trader-v2"

img_re = re.compile(r"^\s*image:\s*(\S+)\s*$")
repo_re = re.compile(r"^\s*agenttrader\.dev/repo_id:\s*(.+?)\s*$")
name_re = re.compile(r"^\s*-\s*name:\s*(\S+)\s*$")
value_re = re.compile(r"^\s*value:\s*(.+?)\s*$")

def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s

def image_tag(image: str):
    if "@" in image:
        return ("digest", image.split("@", 1)[1])
    # Find tag separator after last '/'
    last_slash = image.rfind("/")
    after = image[last_slash + 1 :]
    if ":" not in after:
        return ("missing", "")
    tag = image.rsplit(":", 1)[1]
    return ("tag", tag)

images = {}

for path in files:
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"ISSUE\t{path}\t1\tread_error\tunable to read file: {e}")
        continue

    repo_labels = []
    for i, line in enumerate(lines, start=1):
        m = repo_re.match(line)
        if m:
            repo_labels.append((i, _strip_quotes(m.group(1))))

    if not repo_labels:
        print(f"ISSUE\t{path}\t1\trepo_id_missing\tmissing label agenttrader.dev/repo_id: {required_repo_id}")
    else:
        for (ln, v) in repo_labels:
            if v != required_repo_id:
                print(f"ISSUE\t{path}\t{ln}\trepo_id_mismatch\tagenttrader.dev/repo_id must be '{required_repo_id}', got '{v}'")

    pending_agent_mode = None
    for i, line in enumerate(lines, start=1):
        mi = img_re.match(line)
        if mi:
            img = mi.group(1).strip()
            images.setdefault(img, []).append((path, i))

            # Tag policy checks.
            if "$" in img:
                print(f"ISSUE\t{path}\t{i}\timage_templated\timage reference appears templated (fails safe unless --allow-unknown-images): {img}")
                continue
            kind, tag = image_tag(img)
            if kind == "missing":
                print(f"ISSUE\t{path}\t{i}\timage_tag_missing\timage reference must include a tag or digest (no implicit latest): {img}")
            elif kind == "tag":
                t = tag.strip()
                if t == "" or t == ":":
                    print(f"ISSUE\t{path}\t{i}\timage_tag_empty\timage tag is empty: {img}")
                elif t.lower() == "latest":
                    print(f"ISSUE\t{path}\t{i}\timage_tag_latest\tforbidden image tag ':latest': {img}")
                elif t.lower() == "dev":
                    print(f"ISSUE\t{path}\t{i}\timage_tag_dev\tforbidden image tag ':dev': {img}")

        mn = name_re.match(line)
        if mn:
            pending_agent_mode = mn.group(1).strip()
            continue

        if pending_agent_mode == "AGENT_MODE":
            mv = value_re.match(line)
            if mv:
                v = _strip_quotes(mv.group(1)).strip()
                if v.upper() == "EXECUTE":
                    print(f"ISSUE\t{path}\t{i}\tagent_mode_execute\tforbidden AGENT_MODE=EXECUTE in manifest")
                pending_agent_mode = None

# Emit unique images at the end for the shell to validate.
for img in sorted(images.keys()):
    print(f"IMAGE\t{img}")
PY
)"
fi

images=()
if [[ -n "${scan_out}" ]]; then
  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    kind="$(echo "${line}" | cut -f1)"
    if [[ "${kind}" == "ISSUE" ]]; then
      f="$(echo "${line}" | cut -f2)"
      ln="$(echo "${line}" | cut -f3)"
      code="$(echo "${line}" | cut -f4)"
      msg="$(echo "${line}" | cut -f5-)"
      failures+=("${f}:${ln} [${code}] ${msg}")
    elif [[ "${kind}" == "IMAGE" ]]; then
      img="$(echo "${line}" | cut -f2-)"
      images+=("${img}")
    fi
  done <<< "${scan_out}"
fi

project_for_image() {
  local img="$1"
  if [[ -n "${PROJECT}" ]]; then
    echo "${PROJECT}"
    return 0
  fi
  # Artifact Registry: <region>-docker.pkg.dev/<project>/<repo>/<image>[:tag|@digest]
  if [[ "${img}" == *"-docker.pkg.dev/"* ]]; then
    # shellcheck disable=SC2001
    echo "${img}" | awk -F/ '{print $2}'
    return 0
  fi
  echo ""
}

validate_image_exists() {
  local img="$1"
  if [[ "$img" == *"$"* ]]; then
    return 2
  fi
  local p
  p="$(project_for_image "${img}")"

  if command -v gcloud >/dev/null 2>&1; then
    if [[ -n "${p}" ]]; then
      if gcloud artifacts docker images describe "${img}" --project "${p}" --format='value(image_summary.digest)' >/dev/null 2>&1; then
        return 0
      fi
    else
      if gcloud artifacts docker images describe "${img}" --format='value(image_summary.digest)' >/dev/null 2>&1; then
        return 0
      fi
    fi
  fi

  if command -v docker >/dev/null 2>&1; then
    if docker manifest inspect "${img}" >/dev/null 2>&1; then
      return 0
    fi
  fi

  return 1
}

validated_count=0
unknown_count=0

if [[ "${#images[@]}" -gt 0 ]]; then
  # Uniquify deterministically.
  mapfile -t uniq_images < <(printf '%s\n' "${images[@]}" | LC_ALL=C sort -u)
  for img in "${uniq_images[@]}"; do
    if validate_image_exists "${img}"; then
      validated_count=$((validated_count + 1))
      continue
    fi
    rc=$?
    if [[ "${rc}" -eq 2 ]]; then
      unknown_count=$((unknown_count + 1))
      if [[ "${ALLOW_UNKNOWN_IMAGES}" != "1" ]]; then
        failures+=("[image_unknown] ${img} (templated image ref; pass --allow-unknown-images to override)")
      else
        warnings+=("WARN: image validation skipped (templated): ${img}")
      fi
    else
      if [[ "${ALLOW_UNKNOWN_IMAGES}" != "1" ]]; then
        failures+=("[image_missing] ${img} (not found in Artifact Registry / manifest inspect failed)")
      else
        warnings+=("WARN: image could not be validated (allowed): ${img}")
      fi
    fi
  done
fi

echo "== predeploy_guard (agent-trader-v2) =="
echo "namespace: ${NS}"
echo "k8s_dir:   ${K8S_DIR}"
echo "context:   ${current_ctx:-unknown}"
echo "expected:  ${EXPECTED_CONTEXT:-unknown}"
echo ""

if [[ "${#warnings[@]}" -gt 0 ]]; then
  for w in "${warnings[@]}"; do
    echo "${w}"
  done
  echo ""
fi

if [[ "${#failures[@]}" -gt 0 ]]; then
  echo "FAIL: ${#failures[@]} issue(s) found"
  for e in "${failures[@]}"; do
    echo " - ${e}"
  done
  exit 1
fi

echo "PASS: ${#manifest_files[@]} manifest file(s) scanned; ${validated_count} image(s) validated"

