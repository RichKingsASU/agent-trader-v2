"""
Deployment report helper (v2).

This repo currently uses `scripts/deploy_report.sh` for Kubernetes snapshotting.
This file provides a minimal, reusable helper to prefer `/ops/status` when sampling
service health, with fallback to `/health`/`/healthz`.

TODO: Integrate into deploy_report.sh (or replace it) once a stable list of
service base URLs / port-forward strategy exists.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional


def _get_json(url: str, timeout_s: float = 2.0) -> Optional[dict[str, Any]]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            return json.loads(data)
    except (urllib.error.URLError, ValueError):
        return None


def fetch_ops_status(base_url: str, timeout_s: float = 2.0) -> dict[str, Any]:
    """
    Prefer `/ops/status`. Fallback to `/healthz` then `/health`.
    Returns a dict suitable for markdown reporting.
    """
    base = base_url.rstrip("/")

    ops = _get_json(f"{base}/ops/status", timeout_s=timeout_s)
    if ops is not None:
        status = ops.get("status")
        state = status.get("state") if isinstance(status, dict) else None
        return {"source": "/ops/status", "ops_state": state, "payload": ops}

    hz = _get_json(f"{base}/healthz", timeout_s=timeout_s)
    if hz is not None:
        return {"source": "/healthz", "ops_state": None, "payload": hz}

    h = _get_json(f"{base}/health", timeout_s=timeout_s)
    if h is not None:
        return {"source": "/health", "ops_state": None, "payload": h}

    return {"source": None, "ops_state": None, "payload": None}

