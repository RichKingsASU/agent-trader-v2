from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, Literal, Mapping, Optional, Sequence, Tuple, Union


OptionRight = Literal["call", "put"]


@dataclass(frozen=True)
class OptionContract:
    """
    Normalized option contract fields used by deterministic selection.

    This is intentionally minimal: selection is based on expiry, delta, and moneyness.
    """

    symbol: str
    expiration: date
    strike: float
    right: OptionRight
    delta: Optional[float] = None  # may be missing for illiquid contracts / data feeds

    @staticmethod
    def _num(v: Any) -> Optional[float]:
        if v is None:
            return None
        try:
            x = float(v)
        except Exception:
            return None
        if not math.isfinite(x):
            return None
        return x

    @staticmethod
    def _date(v: Any) -> Optional[date]:
        if v is None:
            return None
        if isinstance(v, date) and not hasattr(v, "hour"):  # date but not datetime
            return v
        s = str(v).strip()
        if not s:
            return None
        # tolerate "YYYY-MM-DD..." strings
        try:
            return date.fromisoformat(s[:10])
        except Exception:
            return None

    @staticmethod
    def _right(v: Any) -> Optional[OptionRight]:
        if v is None:
            return None
        s = str(v).strip().lower()
        if not s:
            return None
        if s in {"c", "call", "calls"}:
            return "call"
        if s in {"p", "put", "puts"}:
            return "put"
        # tolerate Alpaca-ish enum-ish values
        if s.startswith("c"):
            return "call"
        if s.startswith("p"):
            return "put"
        return None

    @classmethod
    def from_any(cls, raw: Union["OptionContract", Mapping[str, Any]]) -> Optional["OptionContract"]:
        if isinstance(raw, OptionContract):
            return raw
        if not isinstance(raw, Mapping):
            return None

        sym = raw.get("symbol") or raw.get("option_symbol") or raw.get("optionSymbol") or raw.get("id")
        sym_s = str(sym).strip().upper() if sym is not None else ""
        if not sym_s:
            return None

        exp = cls._date(raw.get("expiration_date") or raw.get("expiration") or raw.get("expiry"))
        if not exp:
            return None

        strike = cls._num(raw.get("strike_price") or raw.get("strike") or raw.get("strikePrice"))
        if strike is None:
            return None

        right = cls._right(raw.get("type") or raw.get("option_type") or raw.get("right"))
        if not right:
            return None

        greeks = raw.get("greeks") or {}
        if isinstance(greeks, Mapping):
            delta = cls._num(greeks.get("delta"))
        else:
            delta = None
        if delta is None:
            # tolerate top-level delta if present
            delta = cls._num(raw.get("delta"))

        return cls(symbol=sym_s, expiration=exp, strike=float(strike), right=right, delta=delta)


@dataclass(frozen=True)
class SelectionRules:
    """
    Deterministic option selection rules.

    - Expiration: choose the expiration with DTE closest to `target_dte` (configurable).
      If `target_dte` is None, choose the nearest (minimum) DTE.
    - Delta band: filter to abs(delta) within [min,max] (inclusive).
    - ATM: choose the strike closest to underlying (absolute distance).

    Reproducibility is enforced by explicit sorting + tie-breakers.
    """

    target_dte: Optional[int] = None
    dte_max: Optional[int] = None
    delta_band: Tuple[float, float] = (0.30, 0.60)
    # Tie-breaker helper: target delta for "closest delta" tie breaks.
    target_abs_delta: Optional[float] = None
    require_delta: bool = True

    def normalized(self) -> "SelectionRules":
        lo, hi = self.delta_band
        lo_f = float(lo)
        hi_f = float(hi)
        if lo_f > hi_f:
            lo_f, hi_f = hi_f, lo_f
        tgt = self.target_abs_delta
        if tgt is None:
            tgt = (lo_f + hi_f) / 2.0
        return SelectionRules(
            target_dte=self.target_dte,
            dte_max=self.dte_max,
            delta_band=(lo_f, hi_f),
            target_abs_delta=float(tgt),
            require_delta=bool(self.require_delta),
        )


def select_option_contract(
    contracts: Sequence[Union[OptionContract, Mapping[str, Any]]],
    *,
    underlying_price: float,
    right: OptionRight = "call",
    as_of: Optional[date] = None,
    rules: Optional[SelectionRules] = None,
) -> Tuple[Optional[OptionContract], Dict[str, Any]]:
    """
    Deterministically select a single option contract.

    Returns: (selected_contract_or_none, debug_stats)
    """

    if as_of is None:
        as_of = date.today()
    rules_n = (rules or SelectionRules()).normalized()

    underlying = float(underlying_price)
    if not math.isfinite(underlying) or underlying <= 0:
        raise ValueError("underlying_price must be a positive finite number")

    normalized: list[OptionContract] = []
    for c in contracts:
        oc = OptionContract.from_any(c)
        if oc is None:
            continue
        if oc.right != right:
            continue
        normalized.append(oc)

    debug: Dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "right": right,
        "underlying_price": underlying,
        "rules": {
            "target_dte": rules_n.target_dte,
            "dte_max": rules_n.dte_max,
            "delta_band": list(rules_n.delta_band),
            "target_abs_delta": rules_n.target_abs_delta,
            "require_delta": rules_n.require_delta,
        },
        "candidates_in": len(contracts),
        "candidates_normalized": len(normalized),
    }

    # Filter by DTE window
    dte_filtered: list[Tuple[int, OptionContract]] = []
    for oc in normalized:
        dte = (oc.expiration - as_of).days
        if dte < 0:
            continue
        if rules_n.dte_max is not None and dte > int(rules_n.dte_max):
            continue
        dte_filtered.append((int(dte), oc))

    debug["candidates_after_dte"] = len(dte_filtered)
    if not dte_filtered:
        debug["selected"] = None
        debug["reason"] = "no_candidates_after_dte"
        return None, debug

    # Choose expiration deterministically
    # primary: closest to target_dte (or nearest expiry if target_dte is None)
    # tie: smaller DTE, then earlier expiration date.
    def exp_rank(item: Tuple[int, OptionContract]) -> Tuple[int, int, str]:
        dte, oc = item
        if rules_n.target_dte is None:
            return (dte, dte, oc.expiration.isoformat())
        dist = abs(dte - int(rules_n.target_dte))
        return (dist, dte, oc.expiration.isoformat())

    best_exp = min(dte_filtered, key=exp_rank)[1].expiration
    exp_candidates = [(dte, oc) for (dte, oc) in dte_filtered if oc.expiration == best_exp]
    debug["selected_expiration"] = best_exp.isoformat()
    debug["selected_expiration_dte"] = min(d for (d, _oc) in exp_candidates) if exp_candidates else None
    debug["candidates_in_selected_expiration"] = len(exp_candidates)

    # Delta band filter (abs delta)
    lo, hi = rules_n.delta_band
    delta_candidates: list[OptionContract] = []
    missing_delta = 0
    for _dte, oc in exp_candidates:
        if oc.delta is None:
            missing_delta += 1
            if rules_n.require_delta:
                continue
        else:
            ad = abs(float(oc.delta))
            if not (lo <= ad <= hi):
                continue
        delta_candidates.append(oc)

    debug["candidates_missing_delta"] = missing_delta
    debug["candidates_after_delta_band"] = len(delta_candidates)
    if not delta_candidates:
        debug["selected"] = None
        debug["reason"] = "no_candidates_after_delta_band"
        return None, debug

    tgt = float(rules_n.target_abs_delta or 0.0)

    # ATM selection with deterministic tie-breakers:
    # 1) closest strike to underlying (abs distance)
    # 2) closest abs(delta) to target_abs_delta (mid-band by default)
    # 3) lower strike (stable)
    # 4) lexicographically smallest symbol (stable)
    def contract_rank(oc: OptionContract) -> Tuple[float, float, float, str]:
        strike_dist = abs(float(oc.strike) - underlying)
        if oc.delta is None:
            delta_dist = float("inf")
        else:
            delta_dist = abs(abs(float(oc.delta)) - tgt)
        return (strike_dist, delta_dist, float(oc.strike), oc.symbol)

    selected = min(delta_candidates, key=contract_rank)
    debug["selected"] = {
        "symbol": selected.symbol,
        "expiration": selected.expiration.isoformat(),
        "strike": selected.strike,
        "right": selected.right,
        "delta": selected.delta,
    }
    debug["reason"] = "ok"
    return selected, debug


def select_option_symbol(
    contracts: Sequence[Union[OptionContract, Mapping[str, Any]]],
    *,
    underlying_price: float,
    right: OptionRight = "call",
    as_of: Optional[date] = None,
    rules: Optional[SelectionRules] = None,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Convenience wrapper around `select_option_contract()` returning only the symbol."""
    c, dbg = select_option_contract(
        contracts,
        underlying_price=underlying_price,
        right=right,
        as_of=as_of,
        rules=rules,
    )
    return (c.symbol if c else None), dbg

