"""Production smoke: import critical modules and exit 0.

Cloud Run Job deploy must use module-mode args:
  --command "python" --args "-m" --args "backend.jobs.smoke_imports"
"""

from __future__ import annotations

import importlib

from backend.common.ops_log import log_json


MODULES_TO_IMPORT = [
    # Core backend packages
    "backend",
    "backend.common.env",
    "backend.streams",
    # Common runtime deps used by jobs
    "requests",
]


def main() -> int:
    failures: list[str] = []
    for mod in MODULES_TO_IMPORT:
        try:
            importlib.import_module(mod)
            try:
                log_json(intent_type="smoke_imports", severity="INFO", status="ok", module=mod)
            except Exception:
                pass
        except Exception as e:
            failures.append(f"{mod}: {e!r}")

    if failures:
        try:
            log_json(intent_type="smoke_imports", severity="ERROR", status="failed", failures=failures)
        except Exception:
            pass
        return 1

    try:
        log_json(intent_type="smoke_imports", severity="INFO", status="ok_all", modules=MODULES_TO_IMPORT)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

