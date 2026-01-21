"""
Deterministic option contract selection for the gamma scalper.

This module is intentionally **pure and deterministic**:
- It does NOT fetch live option chains.
- It does NOT expand the universe.
- It does NOT optimize (no scoring/ML); it just applies stable rules.

Primary entrypoint:
    select_option_contract(...)

Inputs (required):
- underlying_price: current underlying mid/last price.
- desired_delta_hedge: signed delta hedge amount (share-equivalent direction).
  - If desired_delta_hedge > 0: we need positive delta exposure => choose a CALL.
  - If desired_delta_hedge < 0: we need negative delta exposure => choose a PUT.
- dte_rules: DTE filtering rules (default: 0DTE).
- available_contracts: contracts/snapshots already present in DB/ingest.

Outputs:
- On success: {"decision": "SELECT", "contract_symbol": "...", "metadata": {...}}
- On failure: {"decision": "HOLD", "contract_symbol": None, "metadata": {...}}

Inline examples
---------------

Example 1: choose CALL for positive hedge (0DTE, ATM).

    from datetime import datetime, timezone, date
    from backend.strategies.option_contract_selector import select_option_contract

    contracts = [
        {
            "symbol": "SPY260121C00480000",
            "expiration_date": date(2026, 1, 21),
            "strike_price": 480.0,
            "type": "call",
            "latestQuote": {"bp": 1.00, "ap": 1.10, "t": "2026-01-21T15:30:00Z"},
            "open_interest": 1200,
        },
        {
            "symbol": "SPY260121C00485000",
            "expiration_date": date(2026, 1, 21),
            "strike_price": 485.0,
            "type": "call",
            "latestQuote": {"bp": 0.80, "ap": 0.90, "t": "2026-01-21T15:30:00Z"},
            "open_interest": 900,
        },
    ]

    out = select_option_contract(
        underlying_price=483.2,
        desired_delta_hedge=+25.0,
        available_contracts=contracts,
        as_of_utc=datetime(2026, 1, 21, 15, 30, tzinfo=timezone.utc),
    )
    # => deterministic selection of the closest-to-ATM call (strike 485.0)

Example 2: HOLD when all contracts are stale/illiquid.

    out = select_option_contract(
        underlying_price=483.2,
        desired_delta_hedge=-10.0,
        available_contracts=[{"symbol": "SPY...", "latestQuote": {"bp": 0, "ap": 0, "t": "2026-01-21T13:00:00Z"}}],
    )
    # => {"decision": "HOLD", "metadata": {"reason": "...", ...}}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

OptionRight = str  # "CALL" | "PUT"


@dataclass(frozen=True)
class DteRules:
    """
    DTE filter rules.

    - Default is 0DTE: allow only contracts expiring today (UTC date basis).
    - If allowed_dtes is provided, it takes precedence over min/max/target.
    """

    allowed_dtes: Optional[Tuple[int, ...]] = None
    target_dte: int = 0
    min_dte: Optional[int] = None
    max_dte: Optional[int] = None

    @staticmethod
    def from_input(v: Any) -> "DteRules":
        if v is None:
            return DteRules()
        if isinstance(v, DteRules):
            return v
        if not isinstance(v, Mapping):
            return DteRules()

        allowed = v.get("allowed_dtes") or v.get("allowedDtes") or v.get("allowed")
        if isinstance(allowed, (list, tuple)):
            allowed_dtes = tuple(int(x) for x in allowed if x is not None)
        else:
            allowed_dtes = None

        target = v.get("target_dte") or v.get("targetDte") or v.get("target") or 0
        try:
            target_dte = int(target)
        except Exception:
            target_dte = 0

        min_dte = v.get("min_dte") or v.get("minDte")
        max_dte = v.get("max_dte") or v.get("maxDte")
        try:
            min_dte_i = int(min_dte) if min_dte is not None else None
        except Exception:
            min_dte_i = None
        try:
            max_dte_i = int(max_dte) if max_dte is not None else None
        except Exception:
            max_dte_i = None

        return DteRules(allowed_dtes=allowed_dtes, target_dte=target_dte, min_dte=min_dte_i, max_dte=max_dte_i)

    def allows(self, dte: int) -> bool:
        if self.allowed_dtes is not None:
            return int(dte) in set(self.allowed_dtes)
        lo = self.min_dte if self.min_dte is not None else self.target_dte
        hi = self.max_dte if self.max_dte is not None else self.target_dte
        return int(lo) <= int(dte) <= int(hi)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "allowed_dtes": list(self.allowed_dtes) if self.allowed_dtes is not None else None,
            "target_dte": self.target_dte,
            "min_dte": self.min_dte if self.min_dte is not None else self.target_dte,
            "max_dte": self.max_dte if self.max_dte is not None else self.target_dte,
        }


def select_option_contract(
    *,
    underlying_price: float,
    desired_delta_hedge: float,
    available_contracts: Sequence[Mapping[str, Any]],
    dte_rules: Any = None,
    as_of_utc: Optional[datetime] = None,
    # Hard safety filters (deterministic, not "optimization"):
    max_quote_age_seconds: int = 120,
    min_open_interest: int = 10,
    min_volume: int = 1,
    max_spread_pct: float = 0.35,
) -> Dict[str, Any]:
    """
    Deterministically select a single option contract symbol for hedging.

    Selection order:
    1) Choose CALL/PUT based on sign of desired_delta_hedge.
    2) Apply DTE rules (default 0DTE).
    3) Choose ATM strike (closest strike to underlying_price).
    4) Reject illiquid or stale contracts.
    5) Break ties deterministically.
    """

    now = as_of_utc or datetime.now(timezone.utc)
    rules = DteRules.from_input(dte_rules)

    meta_base: Dict[str, Any] = {
        "underlying_price": float(underlying_price),
        "desired_delta_hedge": float(desired_delta_hedge),
        "as_of_utc": now.isoformat(),
        "dte_rules": rules.to_metadata(),
        "filters": {
            "max_quote_age_seconds": int(max_quote_age_seconds),
            "min_open_interest": int(min_open_interest),
            "min_volume": int(min_volume),
            "max_spread_pct": float(max_spread_pct),
        },
    }

    try:
        px = float(underlying_price)
    except Exception:
        return _hold("invalid_underlying_price", meta_base, extra={"reason": "Underlying price is not a valid number."})
    if not (px > 0):
        return _hold("invalid_underlying_price", meta_base, extra={"reason": "Underlying price must be > 0."})

    try:
        dh = float(desired_delta_hedge)
    except Exception:
        return _hold("invalid_desired_delta_hedge", meta_base, extra={"reason": "Desired delta hedge is not a valid number."})
    if dh == 0.0:
        return _hold("no_hedge_needed", meta_base, extra={"reason": "Desired delta hedge is 0; selector returns HOLD."})

    desired_right: OptionRight = "CALL" if dh > 0 else "PUT"

    candidates: List[dict[str, Any]] = []
    rejected: List[dict[str, Any]] = []

    for raw in available_contracts or []:
        if not isinstance(raw, Mapping):
            continue

        contract_symbol = _get_contract_symbol(raw)
        exp = _get_expiration_date(raw)
        strike = _get_strike(raw)
        right = _get_right(raw)

        # Normalization / minimal validity.
        if not contract_symbol:
            rejected.append({"contract_symbol": None, "reason_code": "missing_contract_symbol"})
            continue
        if exp is None:
            rejected.append({"contract_symbol": contract_symbol, "reason_code": "missing_expiration"})
            continue
        if strike is None or strike <= 0:
            rejected.append({"contract_symbol": contract_symbol, "reason_code": "missing_strike"})
            continue
        if right not in {"CALL", "PUT"}:
            rejected.append({"contract_symbol": contract_symbol, "reason_code": "missing_right"})
            continue
        if right != desired_right:
            rejected.append({"contract_symbol": contract_symbol, "reason_code": "wrong_right", "right": right, "desired": desired_right})
            continue

        dte = _dte_days(exp, now)
        if not rules.allows(dte):
            rejected.append({"contract_symbol": contract_symbol, "reason_code": "dte_not_allowed", "dte": dte})
            continue

        # Quote freshness & liquidity gates.
        q = _extract_quote_snapshot(raw)
        bid = q.get("bid")
        ask = q.get("ask")
        quote_ts = q.get("quote_ts")

        liq_ok, liq_reason, liq_fields = _liquidity_check(
            raw,
            bid=bid,
            ask=ask,
            quote_ts=quote_ts,
            now=now,
            max_quote_age_seconds=max_quote_age_seconds,
            min_open_interest=min_open_interest,
            min_volume=min_volume,
            max_spread_pct=max_spread_pct,
        )
        if not liq_ok:
            rejected.append({"contract_symbol": contract_symbol, "reason_code": liq_reason, **liq_fields})
            continue

        strike_distance = abs(float(strike) - px)
        spread_pct = liq_fields.get("spread_pct")

        candidates.append(
            {
                "contract_symbol": contract_symbol,
                "expiration": exp,
                "dte": dte,
                "right": right,
                "strike": float(strike),
                "strike_distance": float(strike_distance),
                "bid": bid,
                "ask": ask,
                "quote_ts": quote_ts,
                "spread_pct": spread_pct,
                "liquidity": liq_fields,
            }
        )

    if not candidates:
        extra = {
            "reason": "No eligible contracts after applying right/DTE/liquidity/freshness filters.",
            "desired_right": desired_right,
            "contracts_provided": int(len(available_contracts or [])),
            "candidates": 0,
            "rejections": _summarize_rejections(rejected),
        }
        return _hold("no_eligible_contracts", meta_base, extra=extra)

    # Deterministic tie-breaker:
    # 1) closest-to-ATM strike
    # 2) smaller DTE (closer expiry) within allowed window
    # 3) tighter spread (if available)
    # 4) stable lexical contract symbol
    def _k(c: Mapping[str, Any]) -> Tuple[float, int, float, str]:
        sp = c.get("spread_pct")
        try:
            spv = float(sp) if sp is not None else 9e9
        except Exception:
            spv = 9e9
        return (float(c["strike_distance"]), int(c["dte"]), spv, str(c["contract_symbol"]))

    chosen = sorted(candidates, key=_k)[0]

    out_meta = dict(meta_base)
    out_meta.update(
        {
            "decision": "SELECT",
            "desired_right": desired_right,
            "selection": {
                "contract_symbol": chosen["contract_symbol"],
                "right": chosen["right"],
                "strike": chosen["strike"],
                "expiration": chosen["expiration"].isoformat(),
                "dte": chosen["dte"],
                "bid": chosen["bid"],
                "ask": chosen["ask"],
                "quote_ts": chosen["quote_ts"].isoformat() if isinstance(chosen["quote_ts"], datetime) else None,
                "spread_pct": chosen.get("spread_pct"),
                "strike_distance": chosen["strike_distance"],
            },
            "counts": {
                "contracts_provided": int(len(available_contracts or [])),
                "rejected": int(len(rejected)),
                "candidates": int(len(candidates)),
            },
            # Keep observer payload bounded; include only a small sample of rejections.
            "rejections_sample": rejected[:10],
        }
    )

    return {"decision": "SELECT", "contract_symbol": chosen["contract_symbol"], "metadata": out_meta}


def _hold(reason_code: str, meta_base: Mapping[str, Any], *, extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    md = dict(meta_base)
    md["decision"] = "HOLD"
    md["reason_code"] = str(reason_code)
    if extra:
        md.update(dict(extra))
    return {"decision": "HOLD", "contract_symbol": None, "metadata": md}


def _summarize_rejections(rejected: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_code: Dict[str, int] = {}
    for r in rejected or []:
        code = str(r.get("reason_code") or "unknown")
        by_code[code] = by_code.get(code, 0) + 1
    top = sorted(by_code.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"counts_by_reason_code": dict(top), "total": int(len(rejected or []))}


def _dte_days(exp: date, as_of: datetime) -> int:
    try:
        return int((exp - as_of.astimezone(timezone.utc).date()).days)
    except Exception:
        # Fail-closed: unknown DTE -> treat as very far away so it won't be selected.
        return 10_000


def _coerce_payload_dict(v: Any) -> Optional[Dict[str, Any]]:
    if v is None:
        return None
    if isinstance(v, dict):
        return v
    if isinstance(v, Mapping):
        return dict(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            out = json.loads(s)
        except Exception:
            return None
        return out if isinstance(out, dict) else None
    return None


def _walk_dicts(raw: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    """
    Yield dict-like views for a contract object:
    - the raw dict itself
    - raw["payload"] if present
    - raw["details"] / raw["contract"] if present
    - payload["details"] / payload["contract"] if present
    """
    yield raw
    payload = _coerce_payload_dict(raw.get("payload"))
    if payload:
        yield payload
        details = payload.get("details")
        if isinstance(details, Mapping):
            yield details
        contract = payload.get("contract")
        if isinstance(contract, Mapping):
            yield contract
    details = raw.get("details")
    if isinstance(details, Mapping):
        yield details
    contract = raw.get("contract")
    if isinstance(contract, Mapping):
        yield contract


def _get_contract_symbol(raw: Mapping[str, Any]) -> Optional[str]:
    for d in _walk_dicts(raw):
        for k in ("contract_symbol", "contractSymbol", "option_symbol", "optionSymbol", "symbol", "id", "occ_symbol", "occSymbol"):
            v = d.get(k)
            if v is None:
                continue
            s = str(v).strip().upper()
            if s:
                return s
    return None


def _get_expiration_date(raw: Mapping[str, Any]) -> Optional[date]:
    for d in _walk_dicts(raw):
        v = d.get("expiration_date") or d.get("expirationDate") or d.get("expiration") or d.get("expiry") or d.get("exp")
        if v is None:
            continue
        if isinstance(v, date) and not isinstance(v, datetime):
            return v
        if isinstance(v, datetime):
            return v.date()
        s = str(v).strip()
        if not s:
            continue
        # Expect ISO-ish: YYYY-MM-DD...
        try:
            return date.fromisoformat(s[:10])
        except Exception:
            continue
    return None


def _get_strike(raw: Mapping[str, Any]) -> Optional[float]:
    for d in _walk_dicts(raw):
        v = d.get("strike_price") or d.get("strikePrice") or d.get("strike") or d.get("k")
        if v is None:
            continue
        try:
            f = float(v)
        except Exception:
            continue
        if f > 0:
            return f
    return None


def _get_right(raw: Mapping[str, Any]) -> Optional[OptionRight]:
    for d in _walk_dicts(raw):
        v = d.get("right") or d.get("type") or d.get("put_call") or d.get("putCall") or d.get("call_put") or d.get("callPut")
        if v is None:
            continue
        s = str(v).strip().upper()
        if s in {"CALL", "C"}:
            return "CALL"
        if s in {"PUT", "P"}:
            return "PUT"
        if s in {"CALLS"}:
            return "CALL"
        if s in {"PUTS"}:
            return "PUT"
        if s in {"CALL_OPTION", "PUT_OPTION"}:
            return "CALL" if "CALL" in s else "PUT"
    return None


def _parse_ts(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
    # epoch seconds/ms
    if isinstance(v, (int, float)) and v > 0:
        # Heuristic: > 10^12 is ms
        secs = float(v) / 1000.0 if float(v) > 1e12 else float(v)
        try:
            return datetime.fromtimestamp(secs, tz=timezone.utc)
        except Exception:
            return None
    s = str(v).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _extract_quote_snapshot(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Best-effort extraction of (bid, ask, quote_ts) from various shapes:
    - Alpaca snapshot: {"latestQuote": {"bp","ap","t"}}
    - Flat fields: {"bid","ask","quote_time"} etc
    - DB row: {"payload": {...}} handled by _walk_dicts
    """
    bid = None
    ask = None
    quote_ts = None

    for d in _walk_dicts(raw):
        # Nested quote objects
        lq = d.get("latestQuote") or d.get("latest_quote") or d.get("quote") or d.get("latest_quote")
        if isinstance(lq, Mapping):
            if bid is None:
                bid = _num(lq.get("bp") or lq.get("bid_price") or lq.get("bidPrice") or lq.get("bid"))
            if ask is None:
                ask = _num(lq.get("ap") or lq.get("ask_price") or lq.get("askPrice") or lq.get("ask"))
            if quote_ts is None:
                quote_ts = _parse_ts(lq.get("t") or lq.get("timestamp") or lq.get("ts") or lq.get("time"))

        # Flat fields
        if bid is None:
            bid = _num(d.get("bid") or d.get("bid_price") or d.get("bp"))
        if ask is None:
            ask = _num(d.get("ask") or d.get("ask_price") or d.get("ap"))
        if quote_ts is None:
            quote_ts = _parse_ts(d.get("quote_time") or d.get("quoteTime") or d.get("updated_at") or d.get("updatedAt") or d.get("snapshot_time"))

    return {"bid": bid, "ask": ask, "quote_ts": quote_ts}


def _num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _liquidity_check(
    raw: Mapping[str, Any],
    *,
    bid: Optional[float],
    ask: Optional[float],
    quote_ts: Optional[datetime],
    now: datetime,
    max_quote_age_seconds: int,
    min_open_interest: int,
    min_volume: int,
    max_spread_pct: float,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Returns (ok, reason_code, fields).
    Fail-closed: missing key observables => reject.
    """
    fields: Dict[str, Any] = {}

    # Quote staleness (must be present).
    if quote_ts is None:
        return False, "missing_quote_ts", fields
    age_s = (now.astimezone(timezone.utc) - quote_ts.astimezone(timezone.utc)).total_seconds()
    fields["quote_age_seconds"] = float(age_s)
    if age_s < -5:
        return False, "quote_from_future", fields
    if age_s > float(max_quote_age_seconds):
        return False, "stale_quote", fields

    # Bid/ask sanity.
    if bid is None or ask is None:
        return False, "missing_bid_ask", fields
    try:
        b = float(bid)
        a = float(ask)
    except Exception:
        return False, "invalid_bid_ask", fields
    fields["bid"] = b
    fields["ask"] = a
    if not (b > 0 and a > 0 and a >= b):
        return False, "non_marketable_bid_ask", fields

    mid = (a + b) / 2.0
    spr = a - b
    if mid <= 0:
        return False, "invalid_mid", fields
    spread_pct = spr / mid if mid else 9e9
    fields["mid"] = float(mid)
    fields["spread"] = float(spr)
    fields["spread_pct"] = float(spread_pct)
    if spread_pct > float(max_spread_pct):
        return False, "wide_spread", fields

    # Liquidity: require evidence of activity OR depth.
    oi = _extract_open_interest(raw)
    vol = _extract_volume(raw)
    bs, a_s = _extract_quote_sizes(raw)
    fields["open_interest"] = oi
    fields["volume"] = vol
    fields["bid_size"] = bs
    fields["ask_size"] = a_s

    has_oi = oi is not None
    has_vol = vol is not None
    has_sizes = (bs is not None and bs > 0) or (a_s is not None and a_s > 0)

    if has_oi and int(oi) < int(min_open_interest):
        return False, "low_open_interest", fields
    if has_vol and int(vol) < int(min_volume):
        return False, "low_volume", fields

    if (not has_oi) and (not has_vol) and (not has_sizes):
        # Fail-closed per requirements: cannot verify liquidity.
        return False, "unknown_liquidity", fields

    return True, "ok", fields


def _extract_open_interest(raw: Mapping[str, Any]) -> Optional[int]:
    for d in _walk_dicts(raw):
        v = d.get("open_interest") or d.get("openInterest") or d.get("oi")
        if v is None:
            continue
        try:
            return int(v)
        except Exception:
            continue
    return None


def _extract_volume(raw: Mapping[str, Any]) -> Optional[int]:
    for d in _walk_dicts(raw):
        v = d.get("volume") or d.get("vol") or d.get("v")
        if v is None:
            # Alpaca option snapshot daily bar volume: {"dailyBar": {"v": ...}}
            daily = d.get("dailyBar") or d.get("daily_bar")
            if isinstance(daily, Mapping):
                v = daily.get("v") or daily.get("volume")
        if v is None:
            continue
        try:
            return int(v)
        except Exception:
            continue
    return None


def _extract_quote_sizes(raw: Mapping[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    bid_size = None
    ask_size = None
    for d in _walk_dicts(raw):
        lq = d.get("latestQuote") or d.get("latest_quote") or d.get("quote") or d.get("latest_quote")
        if isinstance(lq, Mapping):
            if bid_size is None:
                bid_size = _intish(lq.get("bs") or lq.get("bid_size") or lq.get("bidSize"))
            if ask_size is None:
                ask_size = _intish(lq.get("as") or lq.get("ask_size") or lq.get("askSize"))
        if bid_size is None:
            bid_size = _intish(d.get("bid_size") or d.get("bidSize") or d.get("bs"))
        if ask_size is None:
            ask_size = _intish(d.get("ask_size") or d.get("askSize") or d.get("as"))
    return bid_size, ask_size


def _intish(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return None

