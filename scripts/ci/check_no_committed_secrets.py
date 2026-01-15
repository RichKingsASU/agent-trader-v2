#!/usr/bin/env python3
"""
Environment secrets audit gate (SAFE / READ-ONLY).

This is a deterministic CI guardrail intended to prevent accidental commits of:
- real secret-bearing files (.env, private keys, credential dumps)
- high-confidence secret material embedded in tracked source/config files

Design goals:
- avoid false positives from docs/examples (skip markdown + audit artifacts)
- keep checks fast and dependency-free (stdlib only)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def _git_ls_files() -> list[str]:
    out = subprocess.check_output(["git", "ls-files"], text=True)
    return [line for line in out.splitlines() if line.strip()]


def _is_doc_like(path: str) -> bool:
    p = Path(path)
    if path.startswith("docs/") or path.startswith("audit_artifacts/"):
        return True
    return p.suffix.lower() in {".md", ".rst", ".txt"}


def _is_probably_binary(path: Path) -> bool:
    # Cheap binary check: read a small chunk and look for NUL bytes.
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
        return b"\x00" in chunk
    except Exception:
        return True


@dataclass(frozen=True)
class Violation:
    path: str
    message: str
    detail: str | None = None


# --- File denylist (tracked files that should never be committed) ---
_FORBIDDEN_FILE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Dotenv files are fine as *.example / *.template, but real .env should never be tracked.
    (re.compile(r"(^|/)\.env(\..+)?$"), "Forbidden: committed dotenv file."),
    # Private keys / keystores
    (re.compile(r".*\.(pem|key|p12|pfx|jks)$", re.IGNORECASE), "Forbidden: committed private key / keystore file."),
    # Common SSH private key filenames (public keys are OK)
    (re.compile(r"(^|/)(id_rsa|id_ed25519)$"), "Forbidden: committed SSH private key."),
    # Common credential dumps / configs that often contain secrets
    (re.compile(r"(^|/)\.npmrc$"), "Forbidden: committed .npmrc (may contain auth tokens)."),
    (re.compile(r"(^|/)\.pypirc$"), "Forbidden: committed .pypirc (may contain auth tokens)."),
    (re.compile(r"(^|/)\.aws/credentials$"), "Forbidden: committed AWS shared credentials file."),
    (re.compile(r"(^|/)\.kube/config$"), "Forbidden: committed kubeconfig."),
    (re.compile(r"(^|/)kubeconfig(\..+)?$"), "Forbidden: committed kubeconfig."),
    # Common GCP/Firebase service account key filenames
    (re.compile(r"(^|/)(serviceAccountKey|service-account-key)\.json$", re.IGNORECASE), "Forbidden: committed service account key JSON."),
    (re.compile(r".*service[_-]?account.*\.json$", re.IGNORECASE), "Forbidden: committed service account JSON."),
    (re.compile(r".*credentials.*\.json$", re.IGNORECASE), "Forbidden: committed credentials JSON."),
]

_ALLOWED_FILE_PATTERNS: list[re.Pattern[str]] = [
    # Explicitly allow examples/templates.
    re.compile(r"(^|/)\.env\.example$"),
    re.compile(r"(^|/)\.env\.template$"),
    re.compile(r".*\.env\.yaml\.example$", re.IGNORECASE),
    re.compile(r".*\.example$", re.IGNORECASE),
    # Public keys are fine.
    re.compile(r".*\.pub$", re.IGNORECASE),
]


# --- High-confidence secret content patterns (skip docs) ---
_CONTENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PGP) PRIVATE KEY-----"), "Private key material detected."),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id detected."),
    (re.compile(r"\bASIA[0-9A-Z]{16}\b"), "AWS STS access key id detected."),
    (re.compile(r"\bghp_[0-9A-Za-z]{36}\b"), "GitHub personal access token detected."),
    (re.compile(r"\bgithub_pat_[0-9A-Za-z_]{80,}\b"), "GitHub fine-grained token detected."),
    (re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"), "Slack token detected."),
    (re.compile(r"\bsk_live_[0-9A-Za-z]{10,}\b"), "Stripe live secret key detected."),
]


def _is_allowed(path: str) -> bool:
    return any(r.search(path) for r in _ALLOWED_FILE_PATTERNS)


def _scan_forbidden_files(tracked: list[str]) -> list[Violation]:
    violations: list[Violation] = []
    for f in tracked:
        if _is_allowed(f):
            continue
        for rx, msg in _FORBIDDEN_FILE_PATTERNS:
            if rx.search(f):
                violations.append(Violation(path=f, message=msg))
                break
    return violations


def _scan_content(tracked: list[str]) -> list[Violation]:
    violations: list[Violation] = []
    for f in tracked:
        # Skip docs/audits by design (avoid false positives on explanatory text).
        if _is_doc_like(f):
            continue
        p = Path(f)
        if not p.exists() or not p.is_file():
            continue
        # Keep it fast and safe.
        try:
            if p.stat().st_size > 1_000_000:
                continue
        except OSError:
            continue
        if _is_probably_binary(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for rx, msg in _CONTENT_PATTERNS:
            m = rx.search(text)
            if m:
                # Best-effort: show the first matching line for debugging.
                detail = None
                for line in text.splitlines():
                    if rx.search(line):
                        detail = line.strip()
                        break
                violations.append(Violation(path=f, message=msg, detail=detail))
                break
    return violations


def main() -> int:
    tracked = _git_ls_files()
    file_violations = _scan_forbidden_files(tracked)
    content_violations = _scan_content(tracked)

    if not file_violations and not content_violations:
        print("OK: no committed secret files or high-confidence secret material detected.")
        return 0

    print("ERROR: environment secrets audit gate failed.", file=sys.stderr)
    if file_violations:
        print("", file=sys.stderr)
        print("Forbidden tracked files:", file=sys.stderr)
        for v in file_violations:
            print(f"- {v.path}: {v.message}", file=sys.stderr)

    if content_violations:
        print("", file=sys.stderr)
        print("High-confidence secret material detected in tracked files:", file=sys.stderr)
        for v in content_violations:
            print(f"- {v.path}: {v.message}", file=sys.stderr)
            if v.detail:
                print(f"  > {v.detail}", file=sys.stderr)

    print("", file=sys.stderr)
    print("Remediation:", file=sys.stderr)
    print("- Remove the secret from git history if it was committed.", file=sys.stderr)
    print("- Rotate the credential immediately.", file=sys.stderr)
    print("- Store secrets in a secrets manager and reference via environment variables at runtime.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

