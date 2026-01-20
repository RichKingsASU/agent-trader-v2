"""
Universal execution guard for high-risk scripts.

This module is designed to be added to scripts with minimal intrusion:

    from lib.exec_guard import enforce_execution_policy
    enforce_execution_policy(__file__, sys.argv)

It reads `scripts/script_risk_manifest.yaml` and enforces one of:
  - NEVER_AUTO: always refuse execution
  - MUST_LOCK: refuse unless required flags are present in argv
  - SAFE: allow execution

Safety posture:
  - Fail closed by default (missing/invalid manifest or missing script entry => refuse)
  - Environment-aware messaging (CI vs local), but policy is enforced consistently
"""

from __future__ import annotations

import fnmatch
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(v: object | None) -> bool:
    if v is None:
        return False
    return str(v).strip().lower() in _TRUTHY


def _is_ci() -> bool:
    """
    Best-effort CI detection for clearer error messages.
    """
    if _is_truthy(os.getenv("CI")):
        return True
    # Common CI providers
    if _is_truthy(os.getenv("GITHUB_ACTIONS")):
        return True
    if os.getenv("BUILD_ID") or os.getenv("BUILD_NUMBER"):
        return True
    if os.getenv("KUBERNETES_SERVICE_HOST") and _is_truthy(os.getenv("CI")):
        return True
    return False


@dataclass(frozen=True)
class ScriptPolicy:
    category: str  # NEVER_AUTO | MUST_LOCK | SAFE
    required_flags: tuple[str, ...] = ()
    reason: str | None = None
    matched_by: str | None = None  # path|glob|pattern (for debug)


class ExecGuardError(RuntimeError):
    pass


def _find_repo_root(start: Path) -> Optional[Path]:
    """
    Walk upward looking for a `.git` directory.
    """
    cur = start
    for _ in range(30):  # safety bound
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _repo_relative_posix(repo_root: Path, script_path: Path) -> str:
    try:
        rel = script_path.resolve().relative_to(repo_root.resolve())
        return rel.as_posix()
    except Exception:
        return script_path.as_posix()


def _load_yaml_manifest(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise ExecGuardError(
            "PyYAML is required to enforce execution policy (missing dependency). "
            "Install with: python3 -m pip install --upgrade pyyaml"
        ) from e

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))  # type: ignore[attr-defined]
    except FileNotFoundError as e:
        raise ExecGuardError(f"risk manifest not found: {path}") from e
    except Exception as e:  # noqa: BLE001
        raise ExecGuardError(f"failed to read/parse risk manifest: {path} ({type(e).__name__}: {e})") from e

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ExecGuardError(f"risk manifest must be a mapping/dict at top-level: {path}")
    return raw


def _as_str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if x is not None and str(x).strip() != ""]
    if isinstance(v, (str, int, float, bool)):
        s = str(v).strip()
        return [s] if s else []
    return []


def _normalize_category(v: Any) -> str:
    s = str(v or "").strip().upper()
    return s


def _iter_policy_entries(manifest: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """
    Supports either:
      - { scripts: [ {path|glob|pattern, category, required_flags, reason}, ... ] }
      - { policies: [ ... ] }
      - { entries:  [ ... ] }
      - { <any_key>: [ ... ] } (best-effort fallback for a single list)
    """
    for key in ("scripts", "policies", "entries"):
        v = manifest.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    yield item
            return

    # Best-effort: if there's exactly one list-valued key, treat it as entries.
    list_keys = [k for k, v in manifest.items() if isinstance(v, list)]
    if len(list_keys) == 1:
        v = manifest.get(list_keys[0])
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    yield item


def _match_policy(rel_path_posix: str, manifest: dict[str, Any]) -> Optional[ScriptPolicy]:
    """
    Choose the most specific match:
      - exact `path` match preferred
      - then glob/pattern matches by longest pattern length
    """
    exact: list[ScriptPolicy] = []
    globbed: list[tuple[int, ScriptPolicy]] = []

    for entry in _iter_policy_entries(manifest):
        category = _normalize_category(entry.get("category") or entry.get("rule") or entry.get("risk"))
        if not category:
            continue

        required_flags = tuple(_as_str_list(entry.get("required_flags") or entry.get("requiredFlags") or entry.get("flags")))
        reason = str(entry.get("reason") or entry.get("note") or entry.get("description") or "") or None

        path_val = entry.get("path")
        if path_val is not None:
            p = str(path_val).strip()
            if p and p == rel_path_posix:
                exact.append(
                    ScriptPolicy(
                        category=category,
                        required_flags=required_flags,
                        reason=reason,
                        matched_by=f"path:{p}",
                    )
                )
            continue

        pat_val = entry.get("glob")
        if pat_val is None:
            pat_val = entry.get("pattern")
        if pat_val is None:
            pat_val = entry.get("match")
        if pat_val is None:
            continue

        pat = str(pat_val).strip()
        if not pat:
            continue
        if fnmatch.fnmatch(rel_path_posix, pat):
            globbed.append(
                (
                    len(pat),
                    ScriptPolicy(
                        category=category,
                        required_flags=required_flags,
                        reason=reason,
                        matched_by=f"glob:{pat}",
                    ),
                )
            )

    if exact:
        # If multiple exact entries exist, last one wins (but deterministically keep last).
        return exact[-1]
    if globbed:
        globbed.sort(key=lambda t: (t[0], t[1].matched_by or ""), reverse=True)
        return globbed[0][1]
    return None


def _argv_has_required_flag(argv: list[str], required: str) -> bool:
    """
    Accepts either:
      - exact arg match: "--approve"
      - assignment form: "--env=prod" satisfies required "--env"
    """
    r = (required or "").strip()
    if not r:
        return False
    for a in argv:
        if a == r:
            return True
        if "=" not in r and a.startswith(r + "="):
            return True
    return False


def _die(*, script_rel: str, manifest_path: Path, policy: Optional[ScriptPolicy], message: str) -> None:
    env = "CI" if _is_ci() else "local"
    cat = policy.category if policy else "UNKNOWN"
    required = list(policy.required_flags) if policy else []
    matched_by = policy.matched_by if policy else None

    lines: list[str] = []
    lines.append("EXECUTION REFUSED by exec guard.")
    lines.append(f"- script: {script_rel}")
    lines.append(f"- env: {env}")
    lines.append(f"- manifest: {manifest_path}")
    lines.append(f"- category: {cat}")
    if matched_by:
        lines.append(f"- matched_by: {matched_by}")
    if policy and policy.reason:
        lines.append(f"- reason: {policy.reason}")
    if required:
        lines.append(f"- required_flags: {', '.join(required)}")
    lines.append("")
    lines.append(message.strip())
    print("\n".join(lines), file=sys.stderr)
    raise SystemExit(2)


def enforce_execution_policy(script_file: str, argv: list[str]) -> None:
    """
    Enforce execution policy for the given script.

    Intended usage at the top of high-risk scripts:

        from lib.exec_guard import enforce_execution_policy
        enforce_execution_policy(__file__, sys.argv)
    """
    script_path = Path(script_file).resolve()

    # Prefer finding repo root from the script location; fall back to cwd.
    repo_root = _find_repo_root(script_path.parent) or _find_repo_root(Path.cwd())
    if repo_root is None:
        _die(
            script_rel=script_path.as_posix(),
            manifest_path=Path("scripts/script_risk_manifest.yaml"),
            policy=None,
            message=(
                "Could not locate repo root (no .git directory found). "
                "Fail-closed: refusing execution."
            ),
        )

    manifest_path = repo_root / "scripts" / "script_risk_manifest.yaml"
    script_rel = _repo_relative_posix(repo_root, script_path)

    try:
        manifest = _load_yaml_manifest(manifest_path)
    except ExecGuardError as e:
        _die(
            script_rel=script_rel,
            manifest_path=manifest_path,
            policy=None,
            message=f"{e}\nFail-closed: refusing execution.",
        )

    policy = _match_policy(script_rel, manifest)
    if policy is None:
        _die(
            script_rel=script_rel,
            manifest_path=manifest_path,
            policy=None,
            message=(
                "No policy entry found for this script in the risk manifest.\n"
                "Add an explicit entry (SAFE/MUST_LOCK/NEVER_AUTO). "
                "Fail-closed: refusing execution."
            ),
        )

    category = _normalize_category(policy.category)
    if category not in {"NEVER_AUTO", "MUST_LOCK", "SAFE"}:
        _die(
            script_rel=script_rel,
            manifest_path=manifest_path,
            policy=policy,
            message=(
                f"Unrecognized category '{policy.category}' in risk manifest.\n"
                "Expected one of: NEVER_AUTO, MUST_LOCK, SAFE.\n"
                "Fail-closed: refusing execution."
            ),
        )

    if category == "SAFE":
        return

    if category == "NEVER_AUTO":
        _die(
            script_rel=script_rel,
            manifest_path=manifest_path,
            policy=policy,
            message="Policy NEVER_AUTO: this script is not permitted to auto-execute.",
        )

    # MUST_LOCK
    required = list(policy.required_flags)
    if not required:
        _die(
            script_rel=script_rel,
            manifest_path=manifest_path,
            policy=policy,
            message=(
                "Policy MUST_LOCK requires `required_flags` in the manifest entry, but none were provided.\n"
                "Fail-closed: refusing execution."
            ),
        )

    missing = [r for r in required if not _argv_has_required_flag(argv, r)]
    if missing:
        _die(
            script_rel=script_rel,
            manifest_path=manifest_path,
            policy=policy,
            message=(
                "Policy MUST_LOCK: required flags are missing.\n"
                f"Missing: {', '.join(missing)}\n"
                "Re-run with all required flags present."
            ),
        )

    return

