"""
Dependency parity import smoke checks.

Goal: fail fast in CI if container entrypoint imports are missing.
"""

from __future__ import annotations

import importlib
import sys
import traceback
from dataclasses import dataclass


@dataclass(frozen=True)
class ImportFailure:
    module: str
    error_type: str
    error: str


# Keep this list small and stable: "entrypoint modules" only.
IMPORT_TARGETS: dict[str, tuple[str, ...]] = {
    # strategy-engine container entrypoint imports FastAPI app.
    "strategy-engine": (
        "backend.common.a2a_sdk",  # requires httpx
        "backend.strategy_engine.service",
    ),
    # marketdata-mcp-server container entrypoint.
    "marketdata-mcp-server": (
        "backend.app",
    ),
}


def check_imports(*, services: tuple[str, ...] | None = None) -> list[ImportFailure]:
    failures: list[ImportFailure] = []
    selected = services or tuple(IMPORT_TARGETS.keys())

    for svc in selected:
        modules = IMPORT_TARGETS.get(svc)
        if not modules:
            failures.append(
                ImportFailure(
                    module=f"<service:{svc}>",
                    error_type="ValueError",
                    error=f"Unknown service '{svc}'. Known: {sorted(IMPORT_TARGETS.keys())}",
                )
            )
            continue

        for mod in modules:
            try:
                importlib.import_module(mod)
            except Exception as e:
                failures.append(
                    ImportFailure(
                        module=mod,
                        error_type=type(e).__name__,
                        error=str(e),
                    )
                )
                # fail fast: missing deps should be immediate
                return failures

    return failures


def main(argv: list[str]) -> int:
    # Optional args: list of service names to check. Default: all.
    services = tuple(argv[1:]) if len(argv) > 1 else None
    failures = check_imports(services=services)
    if not failures:
        print("dependency_parity_check: ok")
        return 0

    print("dependency_parity_check: FAILED")
    for f in failures:
        print(f"- import {f.module}: {f.error_type}: {f.error}")
    # Best-effort traceback for the first failure to aid debugging.
    try:
        traceback.print_exc()
    except Exception:
        try:
            sys.stderr.write("dependency_parity_check: traceback_print_failed\n")
            sys.stderr.write(traceback.format_exc() + "\n")
            sys.stderr.flush()
        except Exception:
            pass
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

