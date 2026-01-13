from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Optional, Sequence


@dataclass(frozen=True)
class OptionCandidate:
    """
    Minimal normalized option contract representation used for deterministic selection.

    Notes:
    - `delta` is expected to be signed (+ calls, - puts). Selection can use abs(delta).
    - `contract_symbol` is used as a stable deterministic tie-breaker when present.
    """

    underlying: str
    expiration: date
    right: str  # "CALL" | "PUT" (string to keep dependency-free)
    strike: float
    delta: float
    contract_symbol: Optional[str] = None


@dataclass(frozen=True)
class OptionSelectionConfig:
    """
    Heuristics for selecting a single "best" option from a chain.

    - `expiration_rank`: 0 = nearest expiry, 1 = second nearest, ...
      If the ranked expiry has no candidates, selection will deterministically fall
      forward to the next expiry that has eligible candidates.
    - `delta_min`/`delta_max`: inclusive band.
    - `use_abs_delta`: when True (default), uses abs(delta) for banding so calls/puts
      are treated symmetrically.
    - `target_delta`: optional; if None defaults to midpoint of the band.
    - `right`: optional filter ("CALL" or "PUT"). If None, both are eligible.
    """

    expiration_rank: int = 0
    delta_min: float = 0.30
    delta_max: float = 0.60
    use_abs_delta: bool = True
    target_delta: Optional[float] = None
    right: Optional[str] = None


class NoEligibleOptionsError(RuntimeError):
    pass


def _num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def eligible_candidates(
    candidates: Iterable[OptionCandidate],
    *,
    cfg: OptionSelectionConfig,
) -> list[OptionCandidate]:
    """
    Filter to candidates eligible under the configured delta band (+ optional right).
    """

    out: list[OptionCandidate] = []
    right_filter = (cfg.right or "").strip().upper() or None
    dmin = float(cfg.delta_min)
    dmax = float(cfg.delta_max)
    if dmin > dmax:
        dmin, dmax = dmax, dmin

    for c in candidates:
        if right_filter and str(c.right).strip().upper() != right_filter:
            continue
        d = float(c.delta)
        d_cmp = abs(d) if cfg.use_abs_delta else d
        if dmin <= d_cmp <= dmax:
            out.append(c)
    return out


def select_option_contract(
    candidates: Sequence[OptionCandidate],
    *,
    underlying_price: float,
    cfg: OptionSelectionConfig = OptionSelectionConfig(),
) -> OptionCandidate:
    """
    Deterministically select a single contract from an option chain.

    Selection order:
    1) Filter by delta band (and optional right filter)
    2) Choose nearest expiration (rank configurable via `expiration_rank`)
       - if that expiration has no eligible candidates, deterministically fall forward
         to the next expiration that does.
    3) Choose closest-to-ATM strike within that expiration
    4) Tie-breakers to keep selection deterministic across runtimes/providers
    """

    if not candidates:
        raise NoEligibleOptionsError("No option candidates provided.")

    elig = eligible_candidates(candidates, cfg=cfg)
    if not elig:
        raise NoEligibleOptionsError("No eligible option candidates after delta/right filters.")

    # Group eligible candidates by expiration.
    by_exp: dict[date, list[OptionCandidate]] = {}
    for c in elig:
        by_exp.setdefault(c.expiration, []).append(c)

    expirations = sorted(by_exp.keys())
    if not expirations:
        raise NoEligibleOptionsError("No eligible expirations found.")

    rank = int(cfg.expiration_rank)
    if rank < 0:
        rank = 0

    start_idx = min(rank, len(expirations) - 1)
    chosen_exp: Optional[date] = None
    for i in range(start_idx, len(expirations)):
        exp = expirations[i]
        if by_exp.get(exp):
            chosen_exp = exp
            break
    if chosen_exp is None:
        raise NoEligibleOptionsError("No eligible candidates found in any expiration.")

    exp_candidates = by_exp[chosen_exp]

    # Deterministic total ordering within an expiry.
    target = cfg.target_delta
    if target is None:
        target = (float(cfg.delta_min) + float(cfg.delta_max)) / 2.0

    def sort_key(c: OptionCandidate) -> tuple[float, float, float, str, str]:
        atm_dist = abs(float(c.strike) - float(underlying_price))
        d_cmp = abs(float(c.delta)) if cfg.use_abs_delta else float(c.delta)
        delta_dist = abs(d_cmp - float(target))
        # Prefer lower strikes first for absolute tie (stability + intuitive).
        strike = float(c.strike)
        right = str(c.right).strip().upper()
        sym = (c.contract_symbol or "").strip().upper()
        return (atm_dist, delta_dist, strike, right, sym)

    best = sorted(exp_candidates, key=sort_key)[0]
    return best


def candidate_from_alpaca_snapshot(
    *,
    underlying: str,
    option_symbol: str,
    snapshot: dict[str, Any],
) -> Optional[OptionCandidate]:
    """
    Best-effort adapter from Alpaca option snapshot payload -> OptionCandidate.

    Alpaca snapshot shapes vary slightly by endpoint.
    This function intentionally stays defensive and returns None if required fields
    are missing.
    """

    # Common shapes:
    # - snapshot["greeks"]["delta"]
    # - snapshot["latestQuote"] / snapshot["latestTrade"] etc (not needed here)
    greeks = snapshot.get("greeks") or {}
    delta = _num(greeks.get("delta"))
    if delta is None:
        return None

    # Contract details are sometimes nested under "contract", sometimes top-level.
    contract = snapshot.get("contract") or snapshot.get("option") or snapshot

    exp_s = contract.get("expiration_date") or contract.get("expirationDate") or contract.get("expiration")
    strike = _num(contract.get("strike_price") or contract.get("strike") or contract.get("strikePrice"))
    right = contract.get("type") or contract.get("right") or contract.get("option_type")

    if not exp_s or strike is None or not right:
        return None

    try:
        exp = date.fromisoformat(str(exp_s)[:10])
    except Exception:
        return None

    right_norm = str(right).strip().upper()
    if right_norm in {"C", "CALL"}:
        right_norm = "CALL"
    elif right_norm in {"P", "PUT"}:
        right_norm = "PUT"

    if right_norm not in {"CALL", "PUT"}:
        return None

    return OptionCandidate(
        underlying=str(underlying).strip().upper(),
        expiration=exp,
        right=right_norm,
        strike=float(strike),
        delta=float(delta),
        contract_symbol=str(option_symbol).strip().upper() or None,
    )

