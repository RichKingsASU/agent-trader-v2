"""
Deterministic in-cluster service discovery endpoints.

Defaults are Kubernetes Service DNS names (ClusterIP).
All values may be overridden via environment variables.
"""

from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    if v is None:
        return default
    v = str(v).strip()
    return v or default


# In-cluster defaults (namespace suffix optional; K8s will resolve within the same namespace):
MARKETDATA_BASE_URL: str = _env("MARKETDATA_BASE_URL", "http://agenttrader-marketdata-mcp-server")
STRATEGY_ENGINE_BASE_URL: str = _env("STRATEGY_ENGINE_BASE_URL", "http://agenttrader-strategy-engine")
EXECUTION_AGENT_BASE_URL: str = _env("EXECUTION_AGENT_BASE_URL", "http://agenttrader-execution-agent")

