from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal, Mapping, MutableMapping, Optional, Sequence


OptionRight = Literal["CALL", "PUT"]
RightFilter = Literal["CALL", "PUT", "ANY"]


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _parse_date(v: Any) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    if not s:
        return None
    # Accept YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ etc.
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def _normalize_right(v: Any) -> Optional[OptionRight]:
    if v is None:
        return None
    s = str(v).strip().upper()
    if not s:
        return None
    if s in {"C", "CALL", "CALLS"}:
        return "CALL"
    if s in {"P", "PUT", "PUTS"}:
        return "PUT"
    return None


def _extract_contract_symbol(payload: Mapping[str, Any]) -> Optional[str]:
    for k in ("option_symbol", "optionSymbol", "option_contract_symbol", "symbol", "id", "S", "sym"):
        v = payload.get(k)
        if v is None:
            continue
        s = str(v).strip().upper()
        if s:
            return s
    return None


def _extract_expiration(payload: Mapping[str, Any]) -> Optional[date]:
    for k in ("expiration", "expiry", "expiration_date", "expirationDate"):
        d = _parse_date(payload.get(k))
        if d is not None:
            return d
    return None


def _extract_strike(payload: Mapping[str, Any]) -> Optional[float]:
    for k in ("strike", "strike_price", "strikePrice"):
        f = _to_float(payload.get(k))
        if f is not None:
            return f
    return None


def _extract_right(payload: Mapping[str, Any]) -> Optional[OptionRight]:
    # Common keys: "right", "type", "option_type", "put_call"
    for k in ("right", "type", "option_type", "optionType", "put_call", "putCall"):
        r = _normalize_right(payload.get(k))
        if r is not None:
            return r
    return None


def _extract_delta(payload: Mapping[str, Any]) -> Optional[float]:
    # Common shapes:
    # - {"delta": 0.42}
    # - {"greeks": {"delta": 0.42}}
    # - Alpaca snapshots: {"greeks": {"delta": 0.42}, ...}
    direct = _to_float(payload.get("delta") or payload.get("d"))
    if direct is not None:
        return direct

    greeks = payload.get("greeks") or payload.get("g")
    if isinstance(greeks, Mapping):
        g_delta = _to_float(greeks.get("delta") or greeks.get("d"))
        if g_delta is not None:
            return g_delta

    # Sometimes nested under "snapshot" or "data"
    for k in ("snapshot", "data", "payload"):
        sub = payload.get(k)
        if isinstance(sub, Mapping):
            d = _extract_delta(sub)
            if d is not None:
                return d

    return None


@dataclass(frozen=True)
class OptionSelectionConfig:
    """
    Standardized, deterministic option eligibility & selection.

    Selection order:
    1) Choose expiration by "nearest" rank (among eligible expirations).
    2) Filter by delta band.
    3) Choose closest-to-ATM strike (min |strike - underlying_price|).

    Determinism:
    - Ties are broken by strike (lower wins), then contract symbol (lexicographic).
    - Callers SHOULD pass an explicit `as_of` date to avoid time-dependence.
    """

    # Expiration selection (nearest by date, 0 = nearest)
    expiration_rank: int = 0
    min_dte: int = 0
    max_dte: Optional[int] = None

    # Delta eligibility
    delta_min: float = 0.30
    delta_max: float = 0.60
    use_abs_delta: bool = True

    # Contract side filter
    right: RightFilter = "CALL"


@dataclass(frozen=True)
class SelectedOption:
    contract_symbol: str
    expiration: date
    right: OptionRight
    strike: float
    delta: float
    underlying_price: float
    raw: Mapping[str, Any]


def select_option_contract(
    *,
    contracts: Sequence[Mapping[str, Any]],
    underlying_price: float,
    cfg: OptionSelectionConfig = OptionSelectionConfig(),
    as_of: Optional[date] = None,
) -> SelectedOption:
    """
    Pick a single eligible option contract deterministically.

    Raises:
        ValueError if no contract can be selected.
    """
    if underlying_price <= 0:
        raise ValueError("underlying_price must be > 0")
    if cfg.expiration_rank < 0:
        raise ValueError("expiration_rank must be >= 0")
    if cfg.delta_min < 0 or cfg.delta_max < 0 or cfg.delta_min > cfg.delta_max:
        raise ValueError("invalid delta band")

    as_of_d = as_of or _today_utc()

    # Normalize + initial filters (right + DTE window)
    normalized: list[MutableMapping[str, Any]] = []
    for c in contracts or []:
        if not isinstance(c, Mapping):
            continue
        sym = _extract_contract_symbol(c)
        exp = _extract_expiration(c)
        strike = _extract_strike(c)
        right = _extract_right(c)
        delta = _extract_delta(c)
        if sym is None or exp is None or strike is None or right is None or delta is None:
            continue

        if cfg.right != "ANY" and right != cfg.right:
            continue

        dte = (exp - as_of_d).days
        if dte < cfg.min_dte:
            continue
        if cfg.max_dte is not None and dte > cfg.max_dte:
            continue

        normalized.append(
            {
                "contract_symbol": sym,
                "expiration": exp,
                "strike": float(strike),
                "right": right,
                "delta": float(delta),
                "raw": c,
            }
        )

    if not normalized:
        raise ValueError("no contracts eligible after basic parsing/filters")

    expirations = sorted({x["expiration"] for x in normalized})
    if cfg.expiration_rank >= len(expirations):
        raise ValueError(
            f"expiration_rank={cfg.expiration_rank} out of range (found {len(expirations)} expirations)"
        )
    chosen_exp = expirations[cfg.expiration_rank]

    # Delta band filter (for chosen expiration)
    eligible: list[MutableMapping[str, Any]] = []
    for x in normalized:
        if x["expiration"] != chosen_exp:
            continue
        d = float(x["delta"])
        d_cmp = abs(d) if cfg.use_abs_delta else d
        if cfg.delta_min <= d_cmp <= cfg.delta_max:
            eligible.append(x)

    if not eligible:
        raise ValueError("no contracts eligible after expiration + delta band filters")

    # Closest-to-ATM strike, deterministic tiebreaks.
    # Sort key: (abs(strike-spot), strike, contract_symbol)
    eligible.sort(
        key=lambda x: (
            abs(float(x["strike"]) - float(underlying_price)),
            float(x["strike"]),
            str(x["contract_symbol"]),
        )
    )
    best = eligible[0]

    return SelectedOption(
        contract_symbol=str(best["contract_symbol"]),
        expiration=best["expiration"],
        right=best["right"],
        strike=float(best["strike"]),
        delta=float(best["delta"]),
        underlying_price=float(underlying_price),
        raw=best["raw"],
    )

