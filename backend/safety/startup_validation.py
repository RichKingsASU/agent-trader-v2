from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Iterable, Mapping, NoReturn, Sequence

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env(env: Mapping[str, str], name: str) -> str | None:
    v = env.get(name)
    if v is None:
        return None
    s = str(v).strip()
    return s if s != "" else None


def _fatal_exit(*, intent_type: str, reason_codes: Sequence[str], details: dict | None = None) -> NoReturn:
    payload: dict = {
        "ts": _utc_now_iso(),
        "intent_type": intent_type,
        "reason_codes": list(reason_codes),
    }
    payload["service"] = (
        (os.getenv("SERVICE_NAME") or "").strip()
        or (os.getenv("K_SERVICE") or "").strip()
        or (os.getenv("AGENT_NAME") or "").strip()
        or "unknown"
    )
    payload["env"] = (
        (os.getenv("ENVIRONMENT") or "").strip()
        or (os.getenv("ENV") or "").strip()
        or (os.getenv("APP_ENV") or "").strip()
        or (os.getenv("DEPLOY_ENV") or "").strip()
        or "unknown"
    )
    if details:
        payload["details"] = details

    # Prefer structured log line; also print for container collectors.
    msg = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    try:
        logger.fatal("%s", msg)
    finally:
        try:
            sys.stdout.write(msg + "\n")
            try:
                sys.stdout.flush()
            except Exception:
                pass
        except Exception:
            pass
    raise SystemExit(2)


def validate_required_env_or_exit(
    *,
    env: Mapping[str, str] | None = None,
    required: Iterable[str],
    intent_type: str = "startup_validation_failed",
) -> None:
    """
    Fail-fast if any required env var is missing/empty.
    """
    e = env or os.environ  # type: ignore[assignment]
    missing = [k for k in required if _env(e, k) is None]
    if not missing:
        return
    _fatal_exit(
        intent_type=intent_type,
        reason_codes=[f"{k}_missing" for k in missing],
        details={"required": list(required)},
    )


def validate_agent_mode_or_exit(
    *,
    env: Mapping[str, str] | None = None,
    allowed: set[str],
    var_name: str = "AGENT_MODE",
    intent_type: str = "startup_validation_failed",
) -> None:
    """
    Fail-fast if AGENT_MODE is missing or not in the allowed set (case-insensitive).
    """
    e = env or os.environ  # type: ignore[assignment]
    raw = _env(e, var_name)
    if raw is None:
        _fatal_exit(intent_type=intent_type, reason_codes=[f"{var_name}_missing"])
    mode = str(raw).strip().upper()
    allowed_up = {m.strip().upper() for m in allowed}
    if mode not in allowed_up:
        _fatal_exit(
            intent_type=intent_type,
            reason_codes=[f"{var_name}_invalid"],
            details={"actual": raw, "allowed": sorted(allowed_up)},
        )


def validate_flag_exact_false_or_exit(
    *,
    env: Mapping[str, str] | None = None,
    var_name: str,
    intent_type: str = "startup_validation_failed",
) -> None:
    """
    Fail-fast unless var is present AND exactly "false" (strict, case-sensitive).

    Rationale: for safety-critical flags, strict string matching avoids accidental
    truthy values like "False", "0", "off", etc. slipping through conventions.
    """
    e = env or os.environ  # type: ignore[assignment]
    v = _env(e, var_name)
    if v is None:
        _fatal_exit(intent_type=intent_type, reason_codes=[f"{var_name}_missing"])
    if v != "false":
        _fatal_exit(
            intent_type=intent_type,
            reason_codes=[f"{var_name}_not_false"],
            details={"actual": v, "required_exact": "false"},
        )

