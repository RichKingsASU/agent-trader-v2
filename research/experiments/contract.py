from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import os
import platform
import subprocess
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_git_sha() -> str | None:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
        sha = out.decode("utf-8").strip()
        return sha if sha else None
    except Exception:
        return None


def _safe_git_dirty() -> bool | None:
    try:
        out = subprocess.check_output(["git", "status", "--porcelain"], stderr=subprocess.DEVNULL)
        return bool(out.decode("utf-8").strip())
    except Exception:
        return None


def _build_id() -> str:
    """
    Best-effort build fingerprint.

    This is intentionally lightweight and offline-safe (no network calls).
    """
    sha = _safe_git_sha() or "no-git"
    dirty = _safe_git_dirty()
    dirty_tag = "dirty" if dirty else "clean" if dirty is not None else "unknown"
    py = platform.python_version()
    return f"{sha[:12]}-{dirty_tag}-py{py}"


@dataclass(frozen=True)
class ExperimentSpec:
    """
    Minimal auditable contract for reproducible experiments.

    Required fields (per prompt):
      - experiment_id
      - name
      - description
      - input_dataset (path)
      - parameters (dict)
      - metrics (list)
      - output_dir
      - seed (int default 42)
      - created_at
      - git_sha/build_id (auto injected if available)
    """

    experiment_id: str
    name: str
    description: str
    input_dataset: str
    parameters: dict[str, Any]
    metrics: list[str]
    output_dir: str
    seed: int = 42
    created_at: str = field(default_factory=_utc_now_iso)
    git_sha: str | None = field(default_factory=_safe_git_sha)
    build_id: str = field(default_factory=_build_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def with_overrides(
        self,
        *,
        parameters: dict[str, Any] | None = None,
        output_dir: str | None = None,
        seed: int | None = None,
        git_sha: str | None = None,
        build_id: str | None = None,
    ) -> "ExperimentSpec":
        d = self.to_dict()
        if parameters is not None:
            d["parameters"] = parameters
        if output_dir is not None:
            d["output_dir"] = output_dir
        if seed is not None:
            d["seed"] = seed
        if git_sha is not None:
            d["git_sha"] = git_sha
        if build_id is not None:
            d["build_id"] = build_id
        return ExperimentSpec(**d)


def agent_identity() -> dict[str, Any]:
    """
    Best-effort “agent identity” for provenance.

    This does NOT authenticate or enable trading. It is purely for audit metadata.
    """
    return {
        "user": os.getenv("USER") or os.getenv("USERNAME") or "unknown",
        "hostname": os.getenv("HOSTNAME") or platform.node() or "unknown",
        "agent_identity": os.getenv("AGENT_IDENTITY") or os.getenv("CURSOR_AGENT") or None,
        "ci": bool(os.getenv("CI")),
    }

