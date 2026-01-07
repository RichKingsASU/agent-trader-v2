from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class MarketDataStaleError(RuntimeError):
    pass


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return float(str(raw).strip())


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return int(str(raw).strip())


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class MarketDataHealth:
    ok: bool
    last_tick_epoch_seconds: int | None
    age_seconds: float | None
    max_age_seconds: int
    raw: dict


def get_marketdata_health_url() -> str:
    """
    Where to fetch the marketdata heartbeat.

    - In-cluster default: http://marketdata-mcp-server/healthz
    - Local default: http://127.0.0.1:8080/healthz
    """
    v = os.getenv("MARKETDATA_HEALTH_URL")
    if v:
        return v
    # reasonable default for local/dev
    return "http://127.0.0.1:8080/healthz"


def get_marketdata_max_age_seconds() -> int:
    # Fail-safe default: if not explicitly configured, require freshness within 60s.
    return _env_int("MARKETDATA_MAX_AGE_SECONDS", 60)


def fetch_marketdata_health(*, timeout_seconds: float | None = None) -> MarketDataHealth:
    """
    Fetch heartbeat from marketdata service and compute age locally (fail-safe).
    """
    timeout = timeout_seconds if timeout_seconds is not None else _env_float("MARKETDATA_HEALTH_TIMEOUT_SECONDS", 2.0)
    url = get_marketdata_health_url()
    max_age = get_marketdata_max_age_seconds()

    req = urllib.request.Request(url, headers={"accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200))
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        raise MarketDataStaleError(f"marketdata_health_unreachable url={url} err={e!r}") from e

    try:
        payload = json.loads(body or "{}")
    except Exception as e:  # noqa: BLE001
        raise MarketDataStaleError(f"marketdata_health_invalid_json url={url} status={status}") from e

    last_tick = payload.get("last_tick_epoch_seconds")
    if last_tick is None:
        # Treat missing tick as stale.
        return MarketDataHealth(
            ok=False,
            last_tick_epoch_seconds=None,
            age_seconds=None,
            max_age_seconds=max_age,
            raw=payload if isinstance(payload, dict) else {"payload": payload},
        )

    try:
        last_tick_int = int(last_tick)
    except Exception as e:  # noqa: BLE001
        raise MarketDataStaleError(f"marketdata_health_bad_tick url={url} tick={last_tick!r}") from e

    age = time.time() - float(last_tick_int)
    ok = age <= float(max_age)

    return MarketDataHealth(
        ok=ok,
        last_tick_epoch_seconds=last_tick_int,
        age_seconds=age,
        max_age_seconds=max_age,
        raw=payload if isinstance(payload, dict) else {"payload": payload},
    )


def assert_marketdata_fresh() -> MarketDataHealth:
    """
    Enforce the health contract: stale (or unreachable) marketdata => refuse to proceed.
    """
    # Allow explicit override for local debugging only.
    if _env_bool("MARKETDATA_HEALTH_CHECK_DISABLED", False):
        return MarketDataHealth(ok=True, last_tick_epoch_seconds=None, age_seconds=None, max_age_seconds=get_marketdata_max_age_seconds(), raw={"disabled": True})

    h = fetch_marketdata_health()
    if not h.ok:
        raise MarketDataStaleError(
            f"marketdata_stale age_seconds={h.age_seconds!r} max_age_seconds={h.max_age_seconds} "
            f"last_tick_epoch_seconds={h.last_tick_epoch_seconds} url={get_marketdata_health_url()}"
        )
    return h

