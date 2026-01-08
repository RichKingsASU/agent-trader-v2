from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry
from backend.risk.risk_allocator import allocate_risk

logger = logging.getLogger(__name__)


# --- Vertex AI Gemini defaults (hardcoded to match the known-good Vertex test) ---
VERTEX_PROJECT_ID = "agenttrader-prod"
VERTEX_LOCATION = "global"
VERTEX_MODEL = "gemini-2.5-flash"
VERTEX_HTTP_API_VERSION = "v1"


def _as_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return 0.0
        return float(s)
    raise TypeError(f"Expected number-like value, got {type(v).__name__}")


def get_warm_cache_buying_power_usd(
    *,
    db=None,
    user_id: str = None,
    max_age_s: Optional[float] = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    Backward-compatible wrapper.

    Returns (buying_power_usd, snapshot_dict), where buying_power_usd is sourced from the
    canonical capital state warm-cache reader.
    """
    return get_warm_cache_available_capital_usd(db=db, user_id=user_id, max_age_s=max_age_s)


@dataclass(frozen=True)
class TradeSignal:
    """
    A minimal, execution-oriented signal.

    action: "buy" | "sell" | "flat"
    symbol: e.g. "SPY"
    notional_usd: total dollars intended to deploy (must be <= buying_power)
    """

    action: str
    symbol: str
    notional_usd: float
    reason: str
    raw_model_output: Optional[Dict[str, Any]] = None


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return float(default)
    return float(str(v).strip())


def enforce_affordability(*, signal: TradeSignal, buying_power_usd: float) -> TradeSignal:
    """
    Hard safety gate: never return a trade whose notional exceeds buying power.
    """
    if buying_power_usd <= 0:
        return TradeSignal(
            action="flat",
            symbol=signal.symbol,
            notional_usd=0.0,
            reason="Warm-cache buying power unavailable/zero; refusing to trade.",
            raw_model_output=signal.raw_model_output,
        )

    if signal.action in {"buy", "sell"} and signal.notional_usd > buying_power_usd:
        return TradeSignal(
            action="flat",
            symbol=signal.symbol,
            notional_usd=0.0,
            reason=(
                f"Refusing to trade: requested notional ${signal.notional_usd:,.2f} "
                f"exceeds buying power ${buying_power_usd:,.2f}."
            ),
            raw_model_output=signal.raw_model_output,
        )

    return signal


def _get_vertex_genai_client():
    """
    Vertex AI client configured to match the successful Vertex AI test:
    - location: global
    - project: agenttrader-prod
    - model: gemini-2.5-flash (used by caller)
    - http_options.api_version: v1
    """
    try:
        from google import genai  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Missing dependency 'google-genai'. Add it to requirements and ensure it is installed."
        ) from e

    # The `HttpOptions` type path has varied slightly across versions; handle both.
    http_options = None
    try:
        from google.genai.types import HttpOptions  # type: ignore

        http_options = HttpOptions(api_version=VERTEX_HTTP_API_VERSION)
    except Exception:  # noqa: BLE001
        try:
            from google.genai import types  # type: ignore

            http_options = types.HttpOptions(api_version=VERTEX_HTTP_API_VERSION)
        except Exception:
            # Fall back to a plain dict (supported by some versions).
            http_options = {"api_version": VERTEX_HTTP_API_VERSION}

    kwargs: dict[str, Any] = {
        "vertexai": True,
        "project": VERTEX_PROJECT_ID,
        "location": VERTEX_LOCATION,
    }
    kwargs["http_options"] = http_options

    return genai.Client(**kwargs)


def generate_signal_with_warm_cache(
    *,
    symbol: str,
    market_context: str,
    db=None,
    user_id: str = None,
) -> TradeSignal:
    """
    Generates a trade signal using Vertex AI Gemini with a warm-cache affordability gate.

    Args:
        symbol: Trading symbol (e.g., "SPY")
        market_context: Context information for the model
        db: Firestore client (optional)
        user_id: User ID for multi-tenant support (optional but recommended)

    Behavior:
    - Reads buying power from Firestore warm-cache doc users/{userId}/alpacaAccounts/snapshot.
    - Includes buying power in the prompt as a hard constraint.
    - Validates the returned notional against buying power and forces "flat" if unaffordable.
    """
    buying_power_usd, snapshot = get_warm_cache_buying_power_usd(db=db, user_id=user_id)
    if buying_power_usd <= 0:
        return TradeSignal(
            action="flat",
            symbol=symbol,
            notional_usd=0.0,
            reason="Warm-cache buying power unavailable/zero or snapshot stale; refusing to generate trade.",
            raw_model_output={"snapshot": snapshot},
        )

    client = _get_vertex_genai_client()

    prompt = f"""
You are a trading signal generator. You MUST obey all constraints.

## Constraints (hard safety rules)
- The account buying power is: ${buying_power_usd:,.2f} USD.
- NEVER propose a trade whose notional_usd exceeds buying power.
- If you cannot find a valid trade within buying power, return action="flat".

## Output format
Return a single JSON object with keys:
- action: "buy" | "sell" | "flat"
- symbol: string
- notional_usd: number (0 if flat)
- reason: string

## Market context
Symbol: {symbol}
{market_context}
""".strip()

    # `google-genai` supports structured JSON responses via response_mime_type on many versions.
    # Fall back to plain text if not supported.
    model_output_text: str
    try:
        resp = client.models.generate_content(
            model=VERTEX_MODEL,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        model_output_text = getattr(resp, "text", None) or str(resp)
    except Exception:
        resp = client.models.generate_content(model=VERTEX_MODEL, contents=prompt)
        model_output_text = getattr(resp, "text", None) or str(resp)

    parsed: Dict[str, Any]
    try:
        parsed = json.loads(model_output_text)
    except Exception:
        # Try to recover from "```json ... ```" wrappers.
        cleaned = model_output_text.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(line for line in cleaned.splitlines() if not line.strip().startswith("```")).strip()
        parsed = json.loads(cleaned)

    signal = TradeSignal(
        action=str(parsed.get("action") or "flat").strip().lower(),
        symbol=str(parsed.get("symbol") or symbol).strip().upper(),
        # Risk sizing is enforced deterministically below via allocate_risk().
        notional_usd=_as_float(parsed.get("notional_usd")),
        reason=str(parsed.get("reason") or "").strip() or "No reason provided.",
        raw_model_output=parsed,
    )

    # --- Canonical deterministic risk allocation ---
    #
    # We treat the strategy/model "requested" notional as an input intent, but the final
    # notional is *always* computed by the canonical allocator with portfolio-level caps.
    #
    # Env is read here (NOT inside allocate_risk) so the allocator itself has no hidden globals.
    daily_cap_pct = _env_float("RISK_DAILY_CAP_PCT", 1.0)
    max_strategy_pct = _env_float("RISK_MAX_STRATEGY_ALLOCATION_PCT", 1.0)
    daily_cap_pct = max(0.0, min(1.0, daily_cap_pct))
    max_strategy_pct = max(0.0, min(1.0, max_strategy_pct))

    requested_notional = max(0.0, float(signal.notional_usd or 0.0))
    allocated = allocate_risk(
        strategy_id="vertex_ai_signal",
        signal_confidence=1.0,
        market_state={
            "buying_power_usd": buying_power_usd,
            "daily_risk_cap_pct": daily_cap_pct,
            "max_strategy_allocation_pct": max_strategy_pct,
            "current_allocations_usd": {},  # unknown in this context; caller/orchestrator may provide
            "requested_notional_usd": requested_notional,
            "confidence_scaling": False,  # preserve strategy-requested sizing; only constrain by caps
        },
    )

    sized = TradeSignal(
        action=signal.action,
        symbol=signal.symbol,
        notional_usd=float(allocated),
        reason=signal.reason,
        raw_model_output=signal.raw_model_output,
    )

    # Keep affordability as an additional hard gate (should be redundant if caps <= buying power).
    return enforce_affordability(signal=sized, buying_power_usd=buying_power_usd)

