from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from backend.marketdata.options import alpaca_readonly
from backend.marketdata.options.models import OptionContract, OptionRight, QuoteMetrics, SelectedOptionContract, as_mapping


def _num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _extract_quote_metrics(snapshot: Mapping[str, Any]) -> QuoteMetrics:
    """
    Best-effort parsing across Alpaca snapshot shapes.

    We intentionally keep this permissive because Alpaca fields have differed across:
    - "latestQuote" vs "latest_quote"
    - "bp/ap/bs/as" vs "bidPrice/askPrice/bidSize/askSize"
    """
    snap = as_mapping(snapshot)

    latest_quote = as_mapping(snap.get("latestQuote") or snap.get("latest_quote") or snap.get("quote") or {})
    latest_trade = as_mapping(snap.get("latestTrade") or snap.get("latest_trade") or snap.get("trade") or {})

    bid = _num(latest_quote.get("bp") or latest_quote.get("bid_price") or latest_quote.get("bidPrice") or snap.get("bid"))
    ask = _num(latest_quote.get("ap") or latest_quote.get("ask_price") or latest_quote.get("askPrice") or snap.get("ask"))
    bid_size = _num(latest_quote.get("bs") or latest_quote.get("bid_size") or latest_quote.get("bidSize") or snap.get("bid_size"))
    ask_size = _num(latest_quote.get("as") or latest_quote.get("ask_size") or latest_quote.get("askSize") or snap.get("ask_size"))

    # Volume/open interest are sometimes on the root snapshot, sometimes nested.
    # We treat missing as None (not 0) so sorting can explicitly prefer known values.
    volume = _num(
        snap.get("volume")
        or snap.get("dailyVolume")
        or as_mapping(snap.get("dailyBar") or snap.get("daily_bar") or {}).get("v")
        or as_mapping(snap.get("daily_bar") or {}).get("volume")
        or latest_trade.get("v")
        or latest_trade.get("volume")
    )
    open_interest = _num(snap.get("open_interest") or snap.get("openInterest") or snap.get("oi"))

    # Timestamp keys vary; keep as string.
    snapshot_time = None
    for k in ("t", "timestamp", "updated", "updated_at", "snapshot_time", "snap_time"):
        if k in latest_quote and latest_quote.get(k) is not None:
            snapshot_time = str(latest_quote.get(k))
            break
        if k in snap and snap.get(k) is not None:
            snapshot_time = str(snap.get(k))
            break

    return QuoteMetrics(
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        volume=volume,
        open_interest=open_interest,
        snapshot_time=snapshot_time,
    )


def _dte(*, today: date, exp: date) -> int:
    return int((exp - today).days)


def _best_atm_distance(*, underlying_price: float, contracts: Sequence[OptionContract]) -> float:
    if not contracts:
        return float("inf")
    return min(abs(float(c.strike) - float(underlying_price)) for c in contracts)


def _call_put_strike_bias(*, right: OptionRight, strike: float, underlying_price: float) -> int:
    """
    Tie-breaker for equidistant strikes around spot:
    - Calls: prefer strike >= spot (bias to slightly OTM call)
    - Puts: prefer strike <= spot (bias to slightly OTM put)
    Returns 0 for preferred, 1 for non-preferred (so smaller is better).
    """
    s = float(strike)
    u = float(underlying_price)
    if right == "call":
        return 0 if s >= u else 1
    return 0 if s <= u else 1


def _liquidity_sort_key(
    *,
    contract: OptionContract,
    today: date,
    underlying_price: float,
    quote: QuoteMetrics,
) -> Tuple[float, float, float, float, float, int, int, str]:
    """
    Deterministic key. Lower is better.

    Priority (in order):
    1) Nearest ATM (abs strike distance)
    2) Tighter quoted market (relative spread; missing treated as +inf)
    3) Larger displayed size (bid+ask size; missing treated as 0 => worse via negative)
    4) Higher traded volume (missing treated as 0)
    5) Higher open interest (missing treated as 0)
    6) Sooner expiry (0DTE before 1DTE as tie-breaker)
    7) Slight OTM bias when equidistant around spot
    8) Contract symbol lexicographic for stability
    """
    atm_dist = abs(float(contract.strike) - float(underlying_price))

    rel_spread = quote.rel_spread
    rel_spread_key = float(rel_spread) if rel_spread is not None else float("inf")

    total_size = float(quote.total_size or 0.0)
    volume = float(quote.volume or 0.0)
    oi = float(quote.open_interest or 0.0)

    dte = _dte(today=today, exp=contract.expiration_date)
    bias = _call_put_strike_bias(right=contract.right, strike=contract.strike, underlying_price=underlying_price)

    # Note: negative values because we sort ascending and want "higher is better".
    return (
        float(atm_dist),
        float(rel_spread_key),
        float(-total_size),
        float(-volume),
        float(-oi),
        int(dte),
        int(bias),
        str(contract.symbol),
    )


def select_scalper_contract_from_data(
    *,
    underlying_symbol: str,
    right: OptionRight,
    today: date,
    underlying_price: float,
    contracts: Sequence[OptionContract],
    snapshots_by_symbol: Mapping[str, Any],
    dte_max: int = 1,
) -> SelectedOptionContract:
    """
    Deterministically select a single-leg option contract for scalping.

    Rules enforced:
    - 0..1 DTE only (configurable via dte_max)
    - Nearest ATM (absolute strike distance to spot)
    - Highest liquidity (tightest spread then largest size/volume/OI)
    """
    u = str(underlying_symbol).strip().upper()
    if not u:
        raise ValueError("underlying_symbol is required")
    if float(underlying_price) <= 0:
        raise ValueError("underlying_price must be > 0")
    dte_max = max(0, int(dte_max))

    # Filter to: underlying + right + DTE window
    eligible: List[OptionContract] = []
    for c in contracts:
        if c.underlying_symbol.upper() != u:
            continue
        if c.right != right:
            continue
        dte = _dte(today=today, exp=c.expiration_date)
        if 0 <= dte <= dte_max:
            eligible.append(c)

    if not eligible:
        raise RuntimeError(f"No eligible {u} {right} contracts found for DTE<= {dte_max}")

    # Enforce nearest ATM first: restrict to the minimal distance set.
    best_dist = _best_atm_distance(underlying_price=underlying_price, contracts=eligible)
    # Float tolerance: distances are derived from floats, but strikes are typically discrete.
    tol = 1e-9
    atm = [c for c in eligible if abs(abs(float(c.strike) - float(underlying_price)) - best_dist) <= tol]

    # Enrich with snapshot quote metrics.
    rows: List[Tuple[OptionContract, QuoteMetrics, Mapping[str, Any]]] = []
    for c in atm:
        raw = snapshots_by_symbol.get(c.symbol) if isinstance(snapshots_by_symbol, Mapping) else None
        snap = as_mapping(raw)
        quote = _extract_quote_metrics(snap)
        rows.append((c, quote, snap))

    if not rows:
        raise RuntimeError("No snapshot rows available for ATM candidates")

    # Sort deterministically and pick the best.
    rows_sorted = sorted(
        rows,
        key=lambda t: _liquidity_sort_key(
            contract=t[0],
            today=today,
            underlying_price=underlying_price,
            quote=t[1],
        ),
    )
    best_c, best_q, best_snap = rows_sorted[0]

    return SelectedOptionContract(
        contract_symbol=best_c.symbol,
        underlying_symbol=u,
        right=best_c.right,
        strike=float(best_c.strike),
        expiration_date=best_c.expiration_date,
        dte=_dte(today=today, exp=best_c.expiration_date),
        underlying_price=float(underlying_price),
        quote=best_q,
        raw_snapshot=best_snap,
    )


def select_spy_scalper_contract(
    *,
    right: OptionRight,
    today: Optional[date] = None,
    dte_max: int = 1,
    # Network config
    trading_host: Optional[str] = None,
    data_host: str = "https://data.alpaca.markets",
    stock_feed: Optional[str] = "iex",
    key_id: Optional[str] = None,
    secret_key: Optional[str] = None,
    timeout_s: float = 30.0,
) -> SelectedOptionContract:
    """
    Convenience wrapper for SPY:
    - fetch latest SPY price (read-only)
    - fetch 0..1DTE contracts (read-only)
    - fetch snapshots for ATM candidates (read-only)
    - select deterministically
    """
    td = today or date.today()
    exp_lte = td + timedelta(days=max(0, int(dte_max)))

    underlying_price = alpaca_readonly.fetch_latest_underlying_price(
        symbol="SPY",
        data_host=data_host,
        stock_feed=stock_feed,
        key_id=key_id,
        secret_key=secret_key,
        timeout_s=timeout_s,
    )

    contracts = alpaca_readonly.fetch_option_contracts(
        underlying_symbol="SPY",
        expiration_date_gte=td,
        expiration_date_lte=exp_lte,
        trading_host=trading_host,
        key_id=key_id,
        secret_key=secret_key,
        timeout_s=timeout_s,
    )

    # Pre-filter to ATM set before snapshot call to keep bandwidth low/deterministic.
    eligible = [c for c in contracts if c.right == right and 0 <= _dte(today=td, exp=c.expiration_date) <= max(0, int(dte_max))]
    best_dist = _best_atm_distance(underlying_price=underlying_price, contracts=eligible)
    tol = 1e-9
    atm = [c for c in eligible if abs(abs(float(c.strike) - float(underlying_price)) - best_dist) <= tol]
    symbols = [c.symbol for c in atm]

    snaps = alpaca_readonly.fetch_option_snapshots(
        option_symbols=symbols,
        data_host=data_host,
        key_id=key_id,
        secret_key=secret_key,
        timeout_s=timeout_s,
    )

    return select_scalper_contract_from_data(
        underlying_symbol="SPY",
        right=right,
        today=td,
        underlying_price=float(underlying_price),
        contracts=contracts,
        snapshots_by_symbol=snaps,
        dte_max=dte_max,
    )


def select_spy_scalper_contracts(
    *,
    today: Optional[date] = None,
    dte_max: int = 1,
    trading_host: Optional[str] = None,
    data_host: str = "https://data.alpaca.markets",
    stock_feed: Optional[str] = "iex",
    key_id: Optional[str] = None,
    secret_key: Optional[str] = None,
    timeout_s: float = 30.0,
) -> Dict[str, Any]:
    """
    Returns both CALL and PUT selections (single-leg each).
    """
    call = select_spy_scalper_contract(
        right="call",
        today=today,
        dte_max=dte_max,
        trading_host=trading_host,
        data_host=data_host,
        stock_feed=stock_feed,
        key_id=key_id,
        secret_key=secret_key,
        timeout_s=timeout_s,
    )
    put = select_spy_scalper_contract(
        right="put",
        today=today,
        dte_max=dte_max,
        trading_host=trading_host,
        data_host=data_host,
        stock_feed=stock_feed,
        key_id=key_id,
        secret_key=secret_key,
        timeout_s=timeout_s,
    )
    return {"call": call.to_dict(), "put": put.to_dict()}

