"""Production smoke: import critical modules and exit 0.

Cloud Run Job deploy must use module-mode args:
  --command "python" --args "-m" --args "backend.jobs.smoke_imports"
"""

from __future__ import annotations

import importlib


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
            print(f"OK import {mod}")
        except Exception as e:
            failures.append(f"{mod}: {e!r}")

    if failures:
        print("FAILED imports:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("Smoke imports OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

