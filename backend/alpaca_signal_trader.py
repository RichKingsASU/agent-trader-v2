from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
from uuid import uuid4

from backend.trading.agent_intent.models import (
    AgentIntent,
    AgentIntentConstraints,
    AgentIntentRationale,
    IntentAssetType,
    IntentKind,
    IntentSide,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TradeSignal:
    """
    Lightweight signal object used by tests and warm-cache logic.
    """

    action: str  # "buy" | "sell" | "flat"
    symbol: str
    notional_usd: float
    reason: str = ""


def enforce_affordability(*, signal: TradeSignal, buying_power_usd: float) -> TradeSignal:
    """
    Enforce that BUY signals don't exceed buying power.

    If buying power is unavailable/insufficient, return a flattened (no-op) signal.
    """
    bp = float(buying_power_usd)
    notional = float(signal.notional_usd)
    action = (signal.action or "").strip().lower()

    if action == "buy" and (bp <= 0.0 or notional > bp):
        return TradeSignal(action="flat", symbol=signal.symbol, notional_usd=0.0, reason=signal.reason)
    return signal


# --- Vertex AI Gemini defaults (hardcoded to match the known-good Vertex test) ---
VERTEX_PROJECT_ID = "agenttrader-prod"
VERTEX_LOCATION = "global"
VERTEX_MODEL = "gemini-2.5-flash"
VERTEX_HTTP_API_VERSION = "v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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


def generate_intent_with_vertex(
    *,
    symbol: str,
    market_context: str,
    repo_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    strategy_name: Optional[str] = None,
    strategy_version: Optional[str] = None,
    correlation_id: Optional[str] = None,
    intent_ttl_minutes: int = 5,
) -> AgentIntent:
    """
    Generate an AgentIntent via Vertex AI.

    Safety contract:
    - The model MUST NOT output qty/notional.
    - Capital decisions are made downstream by the risk allocator only.
    """
    client = _get_vertex_genai_client()

    prompt = f"""
You are a trading intent generator. You MUST obey all constraints.

## Constraints (hard safety rules)
- Do NOT include order size, quantity, notional, leverage, or capital amounts.
- If you cannot justify a directional intent, return action="flat".

## Output format
Return a single JSON object with keys:
- action: "buy" | "sell" | "flat"
- confidence: number between 0.0 and 1.0
- reason: string

## Market context
Symbol: {symbol}
{market_context}
""".strip()

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
        cleaned = model_output_text.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(line for line in cleaned.splitlines() if not line.strip().startswith("```")).strip()
        parsed = json.loads(cleaned)

    action = str(parsed.get("action") or "flat").strip().lower()
    side = (
        IntentSide.BUY
        if action == "buy"
        else IntentSide.SELL
        if action == "sell"
        else IntentSide.FLAT
    )
    confidence_raw = parsed.get("confidence")
    confidence: Optional[float] = None
    try:
        if confidence_raw is not None:
            confidence = float(confidence_raw)
    except Exception:
        confidence = None

    now = _utc_now()
    ttl = max(1, int(intent_ttl_minutes))
    return AgentIntent(
        created_at_utc=now,
        repo_id=str(repo_id or os.getenv("REPO_ID") or "unknown_repo"),
        agent_name=str(agent_name or os.getenv("AGENT_NAME") or "alpaca-signal-trader"),
        strategy_name=str(strategy_name or os.getenv("STRATEGY_NAME") or "alpaca_signal"),
        strategy_version=str(strategy_version or os.getenv("STRATEGY_VERSION") or "") or None,
        correlation_id=str(correlation_id or os.getenv("CORRELATION_ID") or uuid4().hex),
        symbol=str(symbol).strip().upper(),
        asset_type=IntentAssetType.EQUITY,
        option=None,
        kind=IntentKind.DIRECTIONAL,
        side=side,
        confidence=confidence,
        rationale=AgentIntentRationale(
            short_reason=str(parsed.get("reason") or "").strip() or "No reason provided.",
            indicators={"raw_model_output": parsed},
        ),
        constraints=AgentIntentConstraints(
            valid_until_utc=(now + timedelta(minutes=ttl)),
            requires_human_approval=True,
            order_type="market",
            time_in_force="day",
            limit_price=None,
            delta_to_hedge=None,
        ),
    )

