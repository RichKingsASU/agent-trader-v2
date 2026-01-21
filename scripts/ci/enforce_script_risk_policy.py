#!/usr/bin/env python3
"""
Script Risk Policy (CI guardrail; SAFE / READ-ONLY).

This guardrail enforces that runnable repository scripts are explicitly tracked in a
manifest with a risk category, and (optionally) that high-risk scripts include an
execution guard invocation.

Why this exists:
- Scripts are frequently added/renamed during incident response. CI must fail fast
  if a new runnable script is not categorized for review.
- The manifest provides an auditable inventory of operational entrypoints.

This script NEVER executes repository scripts. It only scans tracked files.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


MANIFEST_PATH = Path("scripts/ci/script_risk_policy_manifest.json")

# Keep categories small and stable. Adding a new category is a policy change.
ALLOWED_CATEGORIES: set[str] = {"ci", "ops", "deploy", "dev", "execution"}

# Exec-guard invocation patterns (read-only string match).
# We currently enforce this only when manifest marks `requires_exec_guard: true`.
EXEC_GUARD_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bget_kill_switch_state\b"),
    re.compile(r"\bbackend\.common\.kill_switch\b"),
    re.compile(r"\bEXECUTION_HALTED\b"),
]


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    category: str
    requires_exec_guard: bool


def _repo_root() -> Path:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
        if out:
            return Path(out)
    except Exception:
        pass
    return Path.cwd()


def _git_ls_files(repo: Path, patterns: Sequence[str]) -> list[str]:
    out = subprocess.check_output(["git", "ls-files", *patterns], cwd=str(repo), text=True)
    return [line.strip() for line in out.splitlines() if line.strip()]


def _tracked_runnable_scripts(repo: Path) -> list[str]:
    # Scope: runnable scripts in repo root `scripts/` (plus `scripts/ci/**`).
    # Keep this fast: avoid decoding large binary trees; rely on git tracking.
    try:
        files = _git_ls_files(repo, ["scripts"])
        scripts = [p for p in files if p.startswith("scripts/") and p.endswith((".sh", ".py"))]
        return sorted(set(scripts))
    except Exception:
        # Cloud Build (and some CI environments) may not provide a .git checkout.
        # Fall back to a deterministic filesystem walk under scripts/.
        scripts_dir = repo / "scripts"
        if not scripts_dir.exists():
            return []
        found: set[str] = set()
        for p in scripts_dir.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in {".sh", ".py"}:
                continue
            rel = p.relative_to(repo).as_posix()
            if rel.startswith("scripts/"):
                found.add(rel)
        return sorted(found)


def _load_manifest(repo: Path) -> list[ManifestEntry]:
    path = repo / MANIFEST_PATH
    if not path.exists():
        print(f"ERROR: missing script risk manifest: {MANIFEST_PATH}", file=sys.stderr)
        print("Fix: add it (or restore it) in the same PR that changes scripts.", file=sys.stderr)
        raise SystemExit(2)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: failed to parse manifest JSON: {MANIFEST_PATH}", file=sys.stderr)
        print(f"Details: {type(e).__name__}: {e}", file=sys.stderr)
        raise SystemExit(2)

    if not isinstance(raw, dict):
        print(f"ERROR: manifest must be a JSON object: {MANIFEST_PATH}", file=sys.stderr)
        raise SystemExit(2)

    scripts = raw.get("scripts")
    if not isinstance(scripts, list):
        print(f"ERROR: manifest missing 'scripts' array: {MANIFEST_PATH}", file=sys.stderr)
        raise SystemExit(2)

    entries: list[ManifestEntry] = []
    for i, item in enumerate(scripts):
        if not isinstance(item, dict):
            print(f"ERROR: manifest scripts[{i}] must be an object", file=sys.stderr)
            raise SystemExit(2)
        p = item.get("path")
        cat = item.get("category")
        req = item.get("requires_exec_guard", False)
        if not isinstance(p, str) or not p.strip():
            print(f"ERROR: manifest scripts[{i}].path must be a non-empty string", file=sys.stderr)
            raise SystemExit(2)
        if not isinstance(cat, str) or not cat.strip():
            print(f"ERROR: manifest scripts[{i}].category must be a non-empty string", file=sys.stderr)
            raise SystemExit(2)
        if not isinstance(req, bool):
            print(f"ERROR: manifest scripts[{i}].requires_exec_guard must be a boolean", file=sys.stderr)
            raise SystemExit(2)
        entries.append(ManifestEntry(path=p.strip(), category=cat.strip(), requires_exec_guard=req))

    return entries


def _read_text(repo: Path, rel: str) -> str:
    return (repo / rel).read_text(encoding="utf-8", errors="replace")


def _has_exec_guard(text: str) -> bool:
    return any(r.search(text) for r in EXEC_GUARD_PATTERNS)


def _print_list(title: str, items: Iterable[str]) -> None:
    items = list(items)
    if not items:
        return
    print(f"\n{title} ({len(items)}):", file=sys.stderr)
    for it in items:
        print(f" - {it}", file=sys.stderr)


def main(argv: Sequence[str]) -> int:
    _ = argv
    repo = _repo_root()
    entries = _load_manifest(repo)
    tracked = _tracked_runnable_scripts(repo)

    tracked_set = set(tracked)
    manifest_paths = [e.path for e in entries]
    manifest_set = set(manifest_paths)

    dup_counts = Counter(manifest_paths)
    duplicates = sorted([p for p, c in dup_counts.items() if c > 1])

    invalid_categories = sorted(
        [f"{e.path} (category={e.category})" for e in entries if e.category not in ALLOWED_CATEGORIES]
    )

    missing_in_manifest = sorted(tracked_set - manifest_set)
    extra_in_manifest = sorted(manifest_set - tracked_set)

    exec_guard_missing: list[str] = []
    for e in entries:
        if not e.requires_exec_guard:
            continue
        # If the file isn't tracked, it's already reported as an extra entry.
        if e.path not in tracked_set:
            continue
        try:
            text = _read_text(repo, e.path)
        except Exception as ex:  # noqa: BLE001
            exec_guard_missing.append(f"{e.path} (read_error: {type(ex).__name__}: {ex})")
            continue
        if not _has_exec_guard(text):
            exec_guard_missing.append(
                f"{e.path} (category={e.category}) missing exec guard (expected one of: "
                + ", ".join(r.pattern for r in EXEC_GUARD_PATTERNS)
                + ")"
            )

    if any([missing_in_manifest, extra_in_manifest, duplicates, invalid_categories, exec_guard_missing]):
        print("ERROR: script risk policy violations detected.", file=sys.stderr)
        print(f"Manifest: {MANIFEST_PATH}", file=sys.stderr)
        print("Fix: update the manifest to match tracked scripts (and required guard patterns).", file=sys.stderr)

        _print_list("Missing scripts in manifest", missing_in_manifest)
        _print_list("Extra manifest entries (no longer tracked)", extra_in_manifest)
        _print_list("Duplicate manifest entries", [f"{p} (count={dup_counts[p]})" for p in duplicates])
        _print_list("Invalid categories", invalid_categories)
        _print_list("Scripts missing exec guard invocation", exec_guard_missing)

        return 2

    print(f"OK: script risk policy passed ({len(tracked)} scripts validated).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

