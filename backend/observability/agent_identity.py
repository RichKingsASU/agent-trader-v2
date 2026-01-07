from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping


ALLOWED_AGENT_MODES = {"OFF", "OBSERVE", "EXECUTE"}


def _clean(s: Any, *, max_len: int = 256) -> str:
    v = "" if s is None else str(s)
    v = v.replace("\n", " ").replace("\r", " ").strip()
    if len(v) > max_len:
        v = v[: max_len - 1] + "…"
    return v


def _get_git_sha() -> str:
    for k in ("GIT_SHA", "GITHUB_SHA", "COMMIT_SHA", "SHORT_SHA", "BUILD_SHA", "SOURCE_VERSION"):
        v = os.getenv(k)
        if v and v.strip():
            return _clean(v.strip(), max_len=64)
    return "unknown"


def _get_agent_version() -> str:
    v = os.getenv("AGENT_VERSION")
    if v and v.strip():
        return _clean(v.strip(), max_len=64)
    # Default to git sha (replay-friendly), else unknown.
    sha = _get_git_sha()
    return sha if sha and sha != "unknown" else "unknown"


def _read_required_env(name: str) -> str:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        raise ValueError(f"Missing required env var: {name}")
    return _clean(v, max_len=256)


def _read_agent_mode() -> str:
    raw = _read_required_env("AGENT_MODE")
    mode = raw.strip().upper()
    if mode not in ALLOWED_AGENT_MODES:
        raise ValueError(f"Invalid AGENT_MODE: {raw} (allowed: {sorted(ALLOWED_AGENT_MODES)})")
    return mode


def require_identity_env() -> dict[str, str]:
    """
    Validate the institutional agent identity contract.

    Required env vars:
    - REPO_ID
    - AGENT_NAME
    - AGENT_ROLE
    - AGENT_MODE (OFF/OBSERVE/EXECUTE)

    Optional:
    - AGENT_VERSION (defaults to git sha or 'unknown')
    """
    repo_id = _read_required_env("REPO_ID")
    agent_name = _read_required_env("AGENT_NAME")
    agent_role = _read_required_env("AGENT_ROLE")
    agent_mode = _read_agent_mode()
    agent_version = _get_agent_version()
    git_sha = _get_git_sha()

    return {
        "repo_id": repo_id,
        "agent_name": agent_name,
        "agent_role": agent_role,
        "agent_mode": agent_mode,
        "agent_version": agent_version,
        "git_sha": git_sha,
    }


def get_agent_identity() -> dict[str, str]:
    """
    Read agent identity from environment.

    This does NOT validate required fields; call require_identity_env() at process
    startup to fail fast if identity is missing.
    """
    out: dict[str, str] = {}
    for k in ("REPO_ID", "AGENT_NAME", "AGENT_ROLE", "AGENT_MODE", "AGENT_VERSION"):
        v = os.getenv(k)
        if v and v.strip():
            out[k.lower()] = _clean(v.strip(), max_len=256)
    out["git_sha"] = _get_git_sha()
    if "agent_version" not in out:
        out["agent_version"] = _get_agent_version()
    return out


def get_runtime_metadata() -> dict[str, str]:
    """
    Best-effort runtime metadata (safe allowlist, no secrets).
    """
    keys = [
        # Kubernetes
        "HOSTNAME",
        "KUBERNETES_SERVICE_HOST",
        "POD_NAME",
        "POD_NAMESPACE",
        "NODE_NAME",
        # Cloud Run
        "K_SERVICE",
        "K_REVISION",
        "K_CONFIGURATION",
        # Generic
        "WORKLOAD",
        "ENVIRONMENT",
        "LOG_LEVEL",
    ]
    meta: dict[str, str] = {}
    for k in keys:
        v = os.getenv(k)
        if v and v.strip():
            meta[k.lower()] = _clean(v.strip(), max_len=256)
    return meta

