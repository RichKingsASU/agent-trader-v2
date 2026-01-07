#!/bin/sh
#
# CI Build-Time Import Gate
#
# Goal: fail the build if the container image would crash on import of its
# entrypoint module(s). Intended to run in Cloud Build after `docker build`
# and before push/deploy.
#
# Usage:
#   ./scripts/ci_import_gate.sh <image_ref> <module> [<module>...]
#
# Example:
#   ./scripts/ci_import_gate.sh "gcr.io/myproj/myimg:sha" backend.app
#
set -eu

IMAGE_REF="${1:-}"
shift || true

if [ -z "${IMAGE_REF}" ]; then
  echo "❌ IMPORT GATE: missing required <image_ref> argument" >&2
  echo "   Usage: ./scripts/ci_import_gate.sh <image_ref> <module> [<module>...]" >&2
  exit 2
fi

if [ "$#" -eq 0 ]; then
  echo "🟡 IMPORT GATE: no modules provided for ${IMAGE_REF}; skipping"
  exit 0
fi

echo "--- Import gate: ${IMAGE_REF} ---"
echo "Modules: $*"

PY_CODE=$(cat <<'PY'
import importlib
import os
import sys
import traceback

image = os.environ.get("IMPORT_GATE_IMAGE", "<unknown>")
modules = sys.argv[1:]

failed = False
missing = []

for m in modules:
    try:
        importlib.import_module(m)
        print(f"IMPORT_GATE_OK module={m}")
    except ModuleNotFoundError as e:
        failed = True
        missing_name = getattr(e, "name", None) or "<unknown>"
        missing.append(missing_name)
        print(
            f"IMPORT_GATE_FAIL image={image} module={m} missing_module={missing_name}",
            file=sys.stderr,
        )
        # Keep one traceback to show exact import chain failure location.
        traceback.print_exc()
    except Exception as e:  # noqa: BLE001
        failed = True
        print(
            f"IMPORT_GATE_FAIL image={image} module={m} error={e.__class__.__name__}: {e}",
            file=sys.stderr,
        )
        traceback.print_exc()

if failed:
    if missing:
        # Best-effort unique list; order preserved.
        seen = set()
        uniq = []
        for x in missing:
            if x not in seen:
                uniq.append(x)
                seen.add(x)
        print(
            "❌ IMPORT GATE FAILED: missing module(s): " + ", ".join(uniq),
            file=sys.stderr,
        )
    else:
        print("❌ IMPORT GATE FAILED: import error (see traceback above)", file=sys.stderr)
    sys.exit(1)

print("✅ IMPORT GATE PASSED")
PY
)

# Force a deterministic entrypoint so images with ENTRYPOINT ["python"] don't
# double-wrap the interpreter invocation.
docker run --rm \
  -e "IMPORT_GATE_IMAGE=${IMAGE_REF}" \
  --entrypoint python \
  "${IMAGE_REF}" \
  -c "${PY_CODE}" \
  "$@"

