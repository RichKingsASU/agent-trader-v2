#!/usr/bin/env python3
"""
Import all *runtime entrypoint* modules and fail fast on import errors.

Definition (practical, CI-friendly):
- "runtime modules" = Python modules that appear as executable entrypoints in repo-owned
  deployment artifacts (Dockerfiles, shell scripts, YAML manifests), restricted to the
  `backend` package by default.

Why this shape:
- It catches missing dependencies / broken imports before deploy.
- It avoids importing every single internal module (too slow / too side-effecty).
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiscoveredModule:
    module: str
    source: str


_PYTHON_M_RE = re.compile(r"\bpython(?:3)?\b[^\n]*?\s-m\s+([a-zA-Z_][\w\.]*)\b")
_UVICORN_RE = re.compile(r"\buvicorn\b\s+([a-zA-Z_][\w\.]*):([a-zA-Z_]\w*)\b")
_GUNICORN_RE = re.compile(r"\bgunicorn\b\s+([a-zA-Z_][\w\.]*):([a-zA-Z_]\w*)\b")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Import runtime entrypoint modules discovered from deployment artifacts."
    )
    p.add_argument(
        "--prefix",
        action="append",
        default=["backend"],
        help="Module prefix to include (repeatable). Default: backend",
    )
    p.add_argument(
        "--root",
        action="append",
        default=[],
        help=(
            "Repo-relative root directory to scan (repeatable). "
            "Default: infra, backend, scripts, ops, k8s, config, configs"
        ),
    )
    p.add_argument(
        "--max-seconds",
        type=float,
        default=4.5,
        help="Soft time budget for the script (CI should also enforce a hard timeout).",
    )
    p.add_argument(
        "--max-bytes",
        type=int,
        default=512_000,
        help="Skip files larger than this (bytes) to keep scan deterministic and fast.",
    )
    return p.parse_args(argv)


def _repo_root() -> Path:
    # /workspace/scripts/import_runtime_modules.py -> parents[1] == /workspace
    return Path(__file__).resolve().parents[1]


def _default_scan_roots(repo: Path) -> list[Path]:
    roots = ["infra", "backend", "scripts", "ops", "k8s", "config", "configs"]
    out: list[Path] = []
    for r in roots:
        p = repo / r
        if p.exists():
            out.append(p)
    return out


def _iter_scan_files(root: Path) -> list[Path]:
    """
    Scan only artifact types that are likely to contain entrypoints.
    """
    files: list[Path] = []
    # Dockerfiles
    files.extend(root.rglob("Dockerfile"))
    files.extend(root.rglob("Dockerfile.*"))
    # Scripts
    files.extend(root.rglob("*.sh"))
    # Manifests
    files.extend(root.rglob("*.yml"))
    files.extend(root.rglob("*.yaml"))
    return files


def _discover_modules_from_text(txt: str, *, source: str) -> list[DiscoveredModule]:
    out: list[DiscoveredModule] = []

    # `python -m backend.foo`
    for m in _PYTHON_M_RE.finditer(txt):
        out.append(DiscoveredModule(module=m.group(1), source=source))

    # `uvicorn backend.foo:app`
    for m in _UVICORN_RE.finditer(txt):
        out.append(DiscoveredModule(module=m.group(1), source=source))

    # `gunicorn backend.foo:app`
    for m in _GUNICORN_RE.finditer(txt):
        out.append(DiscoveredModule(module=m.group(1), source=source))

    return out


def _discover_modules(repo: Path, *, roots: list[Path], max_bytes: int) -> list[DiscoveredModule]:
    discovered: list[DiscoveredModule] = []
    for root in roots:
        for p in _iter_scan_files(root):
            # Defensive: avoid scanning vendored envs if they happen to be present.
            parts = set(p.parts)
            if ".git" in parts or "site-packages" in parts or "venv" in parts or ".venv" in parts:
                continue
            try:
                if p.stat().st_size > max_bytes:
                    continue
                txt = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            rel = p.relative_to(repo)
            discovered.extend(_discover_modules_from_text(txt, source=str(rel)))
    return discovered


def _apply_safe_env_defaults() -> None:
    """
    The goal is dependency/import failures, not "missing secrets/config".
    Keep this aligned with `scripts/smoke_check_imports.py` where possible.
    """
    os.environ.setdefault("AGENT_MODE", "OFF")
    os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/agenttrader_smoke.db")
    os.environ.setdefault("MARKETDATA_HEALTH_URL", "http://127.0.0.1:8080/healthz")
    os.environ.setdefault("MARKETDATA_HEARTBEAT_URL", "http://127.0.0.1:8080/heartbeat")
    os.environ.setdefault("APCA_API_KEY_ID", "smoke")
    os.environ.setdefault("APCA_API_SECRET_KEY", "smoke")
    os.environ.setdefault("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")


def main(argv: list[str]) -> int:
    started = time.monotonic()
    args = _parse_args(argv)

    repo = _repo_root()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    _apply_safe_env_defaults()

    roots = [repo / r for r in args.root] if args.root else _default_scan_roots(repo)
    discovered = _discover_modules(repo, roots=roots, max_bytes=args.max_bytes)

    prefixes = tuple(str(p).strip() for p in args.prefix if str(p).strip())
    deny = {
        # Common `python -m ...` that are not runtime entrypoints.
        "pip",
        "compileall",
        "unittest",
        "pytest",
        "uvicorn",
    }

    # Deterministic list, with simple provenance.
    seen: dict[str, list[str]] = {}
    for d in discovered:
        mod = d.module.strip()
        if not mod or mod in deny:
            continue
        if prefixes and not any(mod == pfx or mod.startswith(pfx + ".") for pfx in prefixes):
            continue
        seen.setdefault(mod, []).append(d.source)

    modules = sorted(seen.keys())
    if not modules:
        print(
            "ERROR: no runtime modules discovered to import. "
            "If this is unexpected, pass --root/--prefix to adjust scanning.",
            file=sys.stderr,
        )
        return 2

    failures: list[tuple[str, BaseException]] = []
    for mod in modules:
        if (time.monotonic() - started) > float(args.max_seconds):
            print(
                f"ERROR: import check exceeded time budget ({args.max_seconds}s). "
                f"Imported {len(modules) - len(failures)} modules so far; remaining: {len(modules)}",
                file=sys.stderr,
            )
            return 3
        try:
            importlib.import_module(mod)
            src = ", ".join(seen.get(mod, [])[:2])
            more = "" if len(seen.get(mod, [])) <= 2 else f" (+{len(seen.get(mod, [])) - 2} more)"
            print(f"OK   import {mod}  (from {src}{more})")
        except BaseException as e:  # noqa: BLE001 - intentional: import-time failures
            failures.append((mod, e))
            print(f"FAIL import {mod}", file=sys.stderr)
            traceback.print_exc()

    if failures:
        print("", file=sys.stderr)
        print("Runtime module import check failed.", file=sys.stderr)
        for mod, e in failures:
            print(f"- {mod}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - started
    print(f"OK: imported {len(modules)} runtime modules in {elapsed:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

