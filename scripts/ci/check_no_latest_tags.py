#!/usr/bin/env python3
"""
Block forbidden floating container tags like ':latest' (SAFE / READ-ONLY).

Why:
- ':latest' is mutable. It breaks reproducibility and can silently change behavior.
- CI should fail with a precise file:line so fixes are trivial.

Important: We only treat *container image references* as violations.
We intentionally do NOT block unrelated ':latest' usages (e.g. GCP Secret Manager
version selectors like `--update-secrets=FOO=bar:latest`).

What we scan:
- YAML files (*.yml/*.yaml): parsed via PyYAML; we detect images in:
  - any `image:` key (common across k8s, compose, etc.)
  - Cloud Build `steps[].name` (step builder image)
- Dockerfiles (Dockerfile*): we detect `FROM ...:latest`

What we ignore:
- Markdown/docs and audit artifacts (to avoid blocking explanatory text).
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def _git_ls_files(patterns: list[str]) -> list[str]:
    out = subprocess.check_output(["git", "ls-files", *patterns], text=True)
    return [line for line in out.splitlines() if line.strip()]


def _git_ls_all_files() -> list[str]:
    out = subprocess.check_output(["git", "ls-files"], text=True)
    return [line for line in out.splitlines() if line.strip()]


@dataclass(frozen=True)
class Match:
    path: str
    line: int
    snippet: str


RE_FROM_LATEST = re.compile(r"^\s*FROM\s+([^\s]+):latest(\s|$)", re.IGNORECASE)


def _is_ignored(path: str) -> bool:
    p = Path(path)

    # Exclude docs/audits to keep this guard focused on runnable configs.
    if path.startswith("docs/") or path.startswith("audit_artifacts/"):
        return True
    if p.suffix.lower() == ".md":
        return True

    return False


def _is_latest_tag(image_ref: str) -> bool:
    # Allow digests (immutable). If a digest is present, the tag is irrelevant for safety.
    # Example: gcr.io/foo/bar:latest@sha256:...
    if "@sha256:" in image_ref:
        return False
    # Consider only the tag portion before any digest.
    before_digest = image_ref.split("@", 1)[0]
    return before_digest.endswith(":latest")


def _walk_yaml(obj, path: tuple = ()) -> list[tuple[tuple, str]]:
    """
    Return list of (path_tuple, image_ref) for container image references we care about.
    """
    found: list[tuple[tuple, str]] = []

    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "image" and isinstance(v, str):
                found.append((path + (k,), v))
            # Cloud Build: steps[].name is the builder image reference.
            if k == "steps" and isinstance(v, list):
                for idx, step in enumerate(v):
                    if isinstance(step, dict) and isinstance(step.get("name"), str):
                        found.append((path + (k, idx, "name"), step["name"]))
            found.extend(_walk_yaml(v, path + (k,)))
    elif isinstance(obj, list):
        for idx, it in enumerate(obj):
            found.extend(_walk_yaml(it, path + (idx,)))

    return found


def main() -> int:
    try:
        import yaml  # type: ignore
    except Exception as e:  # noqa: BLE001
        print("ERROR: PyYAML is required for ':latest' guardrails.", file=sys.stderr)
        print("Fix:", file=sys.stderr)
        print("  python3 -m pip install --upgrade pyyaml", file=sys.stderr)
        print(f"Details: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    yaml_files = [f for f in _git_ls_files(["*.yml", "*.yaml"]) if not _is_ignored(f)]
    # `git ls-files Dockerfile*` only matches repo-root Dockerfiles. We want all variants,
    # including `infra/Dockerfile.*`, so we filter the full tracked file list.
    dockerfiles = [
        f
        for f in _git_ls_all_files()
        if (Path(f).name.startswith("Dockerfile") and not _is_ignored(f))
    ]

    if not yaml_files and not dockerfiles:
        print("OK: no relevant tracked YAML/Dockerfiles to scan for ':latest'.")
        return 0

    matches: list[Match] = []
    # YAML: parse and inspect image references (no false positives for secret versions).
    for f in yaml_files:
        p = Path(f)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            docs = list(yaml.safe_load_all(text))
        except Exception as e:  # noqa: BLE001
            # YAML syntax errors are handled by validate_yaml_syntax.py; don't double-report here.
            continue

        for d in docs:
            for _path, ref in _walk_yaml(d):
                if isinstance(ref, str) and _is_latest_tag(ref):
                    # Best-effort line reporting: use a simple line scan for the ref.
                    for i, line in enumerate(text.splitlines(), start=1):
                        if ref in line:
                            matches.append(Match(path=f, line=i, snippet=line.strip()))
                            break
                    else:
                        matches.append(Match(path=f, line=1, snippet=f"(unlocated) {ref}"))

    # Dockerfiles: detect FROM ...:latest
    for f in dockerfiles:
        p = Path(f)
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as e:  # noqa: BLE001
            print(f"ERROR: failed to read {f}: {e}", file=sys.stderr)
            return 2
        for i, line in enumerate(lines, start=1):
            if RE_FROM_LATEST.search(line):
                matches.append(Match(path=f, line=i, snippet=line.strip()))

    if matches:
        print("ERROR: forbidden floating tag ':latest' detected.", file=sys.stderr)
        print(
            "Fix: pin images to an immutable tag (e.g. ':1.2.3') or, preferably, a digest ('@sha256:...').",
            file=sys.stderr,
        )
        for m in matches:
            print(f"- {m.path}:{m.line}: contains ':latest'", file=sys.stderr)
            print(f"  > {m.snippet}", file=sys.stderr)
        return 1

    print(f"OK: scanned {len(yaml_files)} YAML files + {len(dockerfiles)} Dockerfiles; no ':latest' image tags found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

