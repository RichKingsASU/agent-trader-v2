from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Literal, Mapping, Optional, Protocol, Sequence

from backend.common.trading_config import get_options_contract_multiplier
from backend.time.nyse_time import parse_ts, to_nyse

OptionType = Literal["call", "put"]


class OptionOrderIntentLike(Protocol):
    """
    Minimal protocol for a "contract not yet resolved" options intent.

    Note: the repo has a v2 `OptionOrderIntent` contract that already includes
    expiration/strike/contract_symbol; this selector intentionally only needs:
    - underlying symbol (`symbol`)
    - desired right (`right`: call|put)
    """

    symbol: str
    right: Any  # allow str/enum; normalized by this module


@dataclass(frozen=True, slots=True)
class OptionSelectorConfig:
    """
    Deterministic selection knobs.
    """

    underlying_default: str = "SPY"
    max_bid_ask_spread: float = 0.10

    # Expiry preference:
    # - before 14:30 ET: prefer 0DTE if available
    # - after 14:30 ET: prefer the *next* expiry when available (avoid late-day 0DTE opens)
    prefer_0dte_before_et: time = time(14, 30)

    # Time guard: after 15:30 ET -> no new positions
    no_new_positions_after_et: time = time(15, 30)

    # Contract multiplier (shares per contract). Default 100.
    multiplier: int = 100


@dataclass(frozen=True, slots=True)
class SyntheticOptionQuote:
    """
    A minimal, provider-agnostic option quote row suitable for deterministic selection.
    """

    expiry: date
    strike: float
    option_type: OptionType
    bid: Optional[float] = None
    ask: Optional[float] = None
    contract_symbol: Optional[str] = None  # provider/OCC symbol if available
    theoretical_delta: Optional[float] = None
    multiplier: Optional[int] = None
    raw: Optional[Mapping[str, Any]] = None

    @property
    def spread(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        b = float(self.bid)
        a = float(self.ask)
        if b <= 0 or a <= 0:
            return None
        return float(a - b)


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """
    Market snapshot passed to the selector (no network calls allowed).
    """

    now_utc: datetime
    underlying_symbol: str
    spot: float
    chain: Sequence[SyntheticOptionQuote]

    @staticmethod
    def from_mapping(obj: Mapping[str, Any]) -> "MarketSnapshot":
        """
        Best-effort adapter for common snapshot shapes in this repo.

        Accepted keys (best-effort):
        - timestamp: now_utc / ts / timestamp / as_of
        - underlying: symbol / underlying_symbol / underlying
        - spot: spot / underlying_price / price / mid
        - chain rows: chain / options / option_chain / contracts
        """
        now_raw = obj.get("now_utc") or obj.get("ts") or obj.get("timestamp") or obj.get("as_of")
        if now_raw is None:
            raise ValueError("MarketSnapshot missing timestamp (now_utc/ts/timestamp/as_of)")
        now_utc = parse_ts(now_raw)

        underlying = str(obj.get("underlying_symbol") or obj.get("symbol") or obj.get("underlying") or "").strip().upper()
        if not underlying:
            raise ValueError("MarketSnapshot missing underlying_symbol")

        spot_raw = obj.get("spot")
        if spot_raw is None:
            spot_raw = obj.get("underlying_price") or obj.get("price") or obj.get("mid")
        try:
            spot = float(spot_raw)
        except Exception as e:  # pragma: no cover
            raise ValueError("MarketSnapshot missing/invalid spot") from e
        if spot <= 0:
            raise ValueError("MarketSnapshot spot must be > 0")

        rows = obj.get("chain") or obj.get("options") or obj.get("option_chain") or obj.get("contracts") or []
        chain: list[SyntheticOptionQuote] = []
        if isinstance(rows, Sequence):
            for item in rows:
                if not isinstance(item, Mapping):
                    continue
                q = _parse_quote_row(item)
                if q is not None:
                    chain.append(q)

        return MarketSnapshot(now_utc=now_utc, underlying_symbol=underlying, spot=spot, chain=tuple(chain))


@dataclass(frozen=True, slots=True)
class ResolvedOptionContract:
    symbol: str  # e.g. SPY_012326C480
    expiry: date
    strike: float
    option_type: OptionType
    multiplier: int
    theoretical_delta: Optional[float] = None


@dataclass(frozen=True, slots=True)
class ContractSelectionError(RuntimeError):
    """
    Fail-closed selection error with explicit reason codes.
    """

    reason: str
    explanation: str
    details: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "explanation": self.explanation,
            "details": dict(self.details or {}),
        }


def resolve_option_contract(
    intent: OptionOrderIntentLike | Mapping[str, Any],
    snapshot: MarketSnapshot | Mapping[str, Any],
    *,
    config: OptionSelectorConfig | None = None,
) -> ResolvedOptionContract:
    """
    Deterministically resolve a single option contract for a gamma scalper.

    Rules (default):
    - Underlying: SPY
    - Expiry: nearest expiry >= today (NY date); 0DTE preferred if before 2:30pm ET
      (after 2:30pm ET, prefer the next expiry when available)
    - Strike:
      - Calls: nearest OTM strike strictly above spot
      - Puts: nearest OTM strike strictly below spot
    - Liquidity guard: skip if bid-ask spread > max
    - Time guard: after 3:30pm ET -> no new positions
    """
    cfg = config or OptionSelectorConfig()

    snap = snapshot if isinstance(snapshot, MarketSnapshot) else MarketSnapshot.from_mapping(snapshot)
    now_et = to_nyse(snap.now_utc)

    if now_et.time() >= cfg.no_new_positions_after_et:
        raise ContractSelectionError(
            reason="TIME_GUARD_NO_NEW_POSITIONS",
            explanation=f"No new positions after {cfg.no_new_positions_after_et.strftime('%H:%M')} ET (now={now_et.time().strftime('%H:%M:%S')}).",
            details={"now_et": now_et.isoformat()},
        )

    underlying = _extract_underlying(intent, default=cfg.underlying_default)
    if underlying != "SPY":
        raise ContractSelectionError(
            reason="UNSUPPORTED_UNDERLYING",
            explanation="Deterministic scalper contract selection is restricted to SPY.",
            details={"underlying": underlying},
        )

    desired_type = _extract_option_type(intent)

    if not snap.chain:
        raise ContractSelectionError(
            reason="EMPTY_CHAIN",
            explanation="Market snapshot option chain is empty; cannot select a contract.",
        )

    # Filter chain to underlying/right and expiries >= today's NY date.
    today_ny = now_et.date()
    eligible = [q for q in snap.chain if q.option_type == desired_type and isinstance(q.expiry, date)]
    expiries = sorted({q.expiry for q in eligible if q.expiry >= today_ny})
    if not expiries:
        raise ContractSelectionError(
            reason="NO_ELIGIBLE_EXPIRY",
            explanation="No expirations found in chain with expiry >= today.",
            details={"today_ny": today_ny.isoformat(), "option_type": desired_type},
        )

    chosen_expiry = _choose_expiry(expiries, today=today_ny, now_et=now_et, cfg=cfg)

    # Strike rule: nearest OTM (strict).
    spot = float(snap.spot)
    strikes = sorted({float(q.strike) for q in eligible if q.expiry == chosen_expiry})
    if not strikes:
        raise ContractSelectionError(
            reason="NO_STRIKES_FOR_EXPIRY",
            explanation="No strikes available for the chosen expiry/right.",
            details={"expiry": chosen_expiry.isoformat(), "option_type": desired_type},
        )

    chosen_strike = _choose_otm_strike(strikes, spot=spot, option_type=desired_type)

    candidates = [q for q in eligible if q.expiry == chosen_expiry and float(q.strike) == float(chosen_strike)]
    if not candidates:
        raise ContractSelectionError(
            reason="NO_STRIKE_MATCH",
            explanation="Chosen strike was not present in the chain for the chosen expiry/right.",
            details={"expiry": chosen_expiry.isoformat(), "strike": chosen_strike, "option_type": desired_type},
        )

    # Liquidity guard: require spread <= max. Missing/invalid quotes are treated as ineligible.
    ok: list[SyntheticOptionQuote] = []
    rejected: list[dict[str, Any]] = []
    for q in candidates:
        spr = q.spread
        if spr is None:
            rejected.append({"contract_symbol": q.contract_symbol, "reason": "MISSING_BID_ASK"})
            continue
        if spr > float(cfg.max_bid_ask_spread):
            rejected.append({"contract_symbol": q.contract_symbol, "reason": "SPREAD_TOO_WIDE", "spread": spr})
            continue
        ok.append(q)

    if not ok:
        raise ContractSelectionError(
            reason="LIQUIDITY_GUARD",
            explanation="All nearest-OTM candidates were rejected by the bid-ask spread guard.",
            details={
                "expiry": chosen_expiry.isoformat(),
                "strike": chosen_strike,
                "option_type": desired_type,
                "max_bid_ask_spread": float(cfg.max_bid_ask_spread),
                "rejected": rejected,
            },
        )

    # Deterministic tie-breaker: tightest spread, then provider symbol lexicographic.
    best = sorted(
        ok,
        key=lambda q: (
            float(q.spread or float("inf")),
            str(q.contract_symbol or "").upper(),
        ),
    )[0]

    mult = int(best.multiplier or cfg.multiplier or get_options_contract_multiplier())
    if mult <= 0:  # pragma: no cover
        mult = 100

    return ResolvedOptionContract(
        symbol=format_compact_option_symbol(underlying=underlying, expiry=chosen_expiry, option_type=desired_type, strike=chosen_strike),
        expiry=chosen_expiry,
        strike=float(chosen_strike),
        option_type=desired_type,
        multiplier=mult,
        theoretical_delta=_safe_float(best.theoretical_delta),
    )


def format_compact_option_symbol(*, underlying: str, expiry: date, option_type: OptionType, strike: float) -> str:
    """
    Format: <UNDERLYING>_<MMDDYY><C|P><STRIKE>
      Example: SPY_012326C480

    Strike formatting:
    - integer strikes: "480"
    - fractional strikes: '.' replaced with 'p' and trailing zeros removed (e.g. 480.5 -> "480p5")
    """
    u = str(underlying or "").strip().upper()
    if not u:
        raise ValueError("underlying is required")
    cp = "C" if option_type == "call" else "P"
    mmddyy = expiry.strftime("%m%d%y")

    s = float(strike)
    # stable strike string: up to 6dp, then trim
    raw = f"{s:.6f}".rstrip("0").rstrip(".")
    raw = raw.replace(".", "p")
    return f"{u}_{mmddyy}{cp}{raw}"


def _choose_expiry(expiries: Sequence[date], *, today: date, now_et: datetime, cfg: OptionSelectorConfig) -> date:
    # Before 14:30 ET: prefer 0DTE if available (today first).
    if now_et.time() < cfg.prefer_0dte_before_et:
        return min(expiries)

    # After 14:30 ET: prefer the next expiry if 0DTE exists (avoid late-day opens).
    if today in expiries:
        future = [d for d in expiries if d > today]
        if future:
            return min(future)
    return min(expiries)


def _choose_otm_strike(strikes: Sequence[float], *, spot: float, option_type: OptionType) -> float:
    u = float(spot)
    if option_type == "call":
        above = [s for s in strikes if float(s) > u]
        if not above:
            raise ContractSelectionError(
                reason="NO_OTM_STRIKE",
                explanation="No OTM call strikes were available above spot.",
                details={"spot": u, "option_type": option_type},
            )
        return min(above)

    below = [s for s in strikes if float(s) < u]
    if not below:
        raise ContractSelectionError(
            reason="NO_OTM_STRIKE",
            explanation="No OTM put strikes were available below spot.",
            details={"spot": u, "option_type": option_type},
        )
    return max(below)


def _extract_underlying(intent: OptionOrderIntentLike | Mapping[str, Any], *, default: str) -> str:
    if isinstance(intent, Mapping):
        sym = intent.get("symbol") or intent.get("underlying_symbol") or intent.get("underlying")
    else:
        sym = getattr(intent, "symbol", None)
    s = str(sym or default).strip().upper()
    return s


def _extract_option_type(intent: OptionOrderIntentLike | Mapping[str, Any]) -> OptionType:
    raw = None
    if isinstance(intent, Mapping):
        raw = intent.get("right") or intent.get("option_type") or intent.get("type")
    else:
        raw = getattr(intent, "right", None)
    s = str(raw or "").strip().lower()
    if s in {"call", "c"}:
        return "call"
    if s in {"put", "p"}:
        return "put"
    raise ValueError(f"Unsupported option_type/right: {raw!r}")


def _parse_quote_row(item: Mapping[str, Any]) -> Optional[SyntheticOptionQuote]:
    # expiry (YYYY-MM-DD)
    exp_raw = item.get("expiry") or item.get("expiration") or item.get("expiration_date") or item.get("exp")
    if exp_raw is None:
        return None
    try:
        exp = date.fromisoformat(str(exp_raw)[:10])
    except Exception:
        return None

    # strike
    try:
        strike = float(item.get("strike") or item.get("strike_price") or item.get("strikePrice"))
    except Exception:
        return None

    # type
    t_raw = item.get("option_type") or item.get("right") or item.get("type")
    try:
        opt_type = _normalize_option_type(t_raw)
    except Exception:
        return None

    bid = _safe_float(item.get("bid") or item.get("bp") or item.get("bid_price"))
    ask = _safe_float(item.get("ask") or item.get("ap") or item.get("ask_price"))

    # delta (best-effort)
    delta = _safe_float(item.get("theoretical_delta") or item.get("delta"))
    if delta is None and isinstance(item.get("greeks"), Mapping):
        delta = _safe_float(item["greeks"].get("delta"))

    mult = _safe_int(item.get("multiplier") or item.get("contract_multiplier"))

    sym = item.get("symbol") or item.get("contract_symbol") or item.get("option_symbol") or item.get("occ_symbol")
    sym_s = str(sym).strip().upper() if sym is not None else None
    sym_s = sym_s or None

    return SyntheticOptionQuote(
        expiry=exp,
        strike=strike,
        option_type=opt_type,
        bid=bid,
        ask=ask,
        contract_symbol=sym_s,
        theoretical_delta=delta,
        multiplier=mult,
        raw=dict(item),
    )


def _normalize_option_type(v: Any) -> OptionType:
    s = str(v or "").strip().lower()
    if s in {"call", "c"}:
        return "call"
    if s in {"put", "p"}:
        return "put"
    raise ValueError(f"bad option_type: {v!r}")


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        return int(v) if float(v).is_integer() else None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None

