#!/usr/bin/env python3
"""
LOCAL-ONLY AGENT SIMULATION HARNESS (TEST-ONLY)
================================================

Purpose
-------
This script is a **SAFE**, **local** test harness to simulate multiple cooperating
agents *without*:
- broker calls
- execution services
- HTTP/network calls
- Firestore/DB writes
- credentials

It generates synthetic market/option data for SPY and runs the pipeline:

  MarketEvent
    → GammaScalper
    → OptionContractSelector
    → OptionOrderIntent
    → OptionsRiskEngine
    → ShadowOptionsExecutor
    → Observer / Explainer

Run
---
  python scripts/run_agent_simulation.py

Controls
--------
- --steps N
- --start-time HH:MM            (America/New_York)
- --force-negative-gex          (forces dealer gamma exposure negative)
- --dry-run / --no-dry-run      (default: dry-run)

Safety guarantees (MANDATORY)
-----------------------------
This file is self-contained and uses Python stdlib only.
It also installs runtime guards that *refuse* any network usage.

If you need to integrate with real services, do it elsewhere — not here.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional, Sequence, Tuple

try:
    # Python 3.9+: stdlib timezone database
    from zoneinfo import ZoneInfo
except Exception as e:  # pragma: no cover
    raise SystemExit(
        "ERROR: zoneinfo not available. Use Python 3.9+.\n"
        f"Import error: {e}"
    )


# -----------------------------
# Safety guards (no network)
# -----------------------------

def _install_no_network_guards() -> None:
    """
    Hard guard: forbid any outbound network calls from this process.

    This is a **test harness** and must never talk to HTTP/brokers/DBs.
    """

    # Guard low-level sockets (covers most HTTP clients).
    import socket  # stdlib

    def _refuse(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError(
            "REFUSED: network access is disabled in scripts/run_agent_simulation.py "
            "(test-only agent simulation harness)."
        )

    socket.create_connection = _refuse  # type: ignore[assignment]

    _orig_socket = socket.socket

    class _GuardedSocket(_orig_socket):  # type: ignore[misc]
        def connect(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            _refuse()

        def connect_ex(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            _refuse()

    socket.socket = _GuardedSocket  # type: ignore[assignment]

    # Guard common stdlib HTTP entrypoints (belt-and-suspenders).
    import http.client  # stdlib
    import urllib.request  # stdlib

    http.client.HTTPConnection.connect = _refuse  # type: ignore[assignment]
    http.client.HTTPSConnection.connect = _refuse  # type: ignore[assignment]
    urllib.request.urlopen = _refuse  # type: ignore[assignment]


def _assert_forbidden_imports_absent() -> None:
    """
    Extra safety: fail fast if someone accidentally adds forbidden imports.
    """

    forbidden_prefixes = (
        # Explicitly forbidden by the task.
        "execution_service",
        "alpaca",
        "alpaca_trade_api",
        # Typical HTTP clients we also don’t want here.
        "requests",
        "httpx",
        "aiohttp",
        # Cloud/DB clients we must not use here.
        "google.cloud",
        "firebase_admin",
        "pymongo",
        "psycopg2",
        "sqlalchemy",
    )
    loaded = sorted(sys.modules.keys())
    offenders: list[str] = []
    for m in loaded:
        for p in forbidden_prefixes:
            if m == p or m.startswith(p + "."):
                offenders.append(m)
                break
    if offenders:
        raise SystemExit(
            "REFUSED: forbidden modules loaded in this test harness.\n"
            f"Offenders: {offenders}"
        )


# Install guards immediately on import/run.
_install_no_network_guards()
_assert_forbidden_imports_absent()


# -----------------------------
# Data model (synthetic)
# -----------------------------

ET = ZoneInfo("America/New_York")
SYMBOL = "SPY"
CONTRACT_MULTIPLIER = 100  # standard US equity options


@dataclass(frozen=True)
class OptionGreekSnapshot:
    """
    Synthetic option snapshot.

    This is intentionally simplified; the goal is deterministic pipeline testing,
    not pricing accuracy.
    """

    expiry: date
    strike: float
    right: str  # "C" or "P"
    mid: float
    delta: float
    gamma: float
    vega: float
    theta: float
    iv: float
    open_interest: int

    @property
    def symbol(self) -> str:
        # Simplified OCC-like string for debugging (not meant for brokerage).
        ymd = self.expiry.strftime("%y%m%d")
        strike_int = int(round(self.strike * 1000))
        return f"{SYMBOL}_{ymd}{self.right}_{strike_int}"


@dataclass(frozen=True)
class MarketEvent:
    ts_et: datetime
    symbol: str
    spot: float
    spot_change_1m: float
    gex: float
    chain: Tuple[OptionGreekSnapshot, ...]


@dataclass(frozen=True)
class GammaSignal:
    ts_et: datetime
    symbol: str
    regime: str  # "NEG_GEX" or "POS_GEX"
    bias: str  # "MEAN_REVERT" or "TREND"
    strength: float  # 0..1
    note: str


@dataclass(frozen=True)
class OptionContractChoice:
    ts_et: datetime
    symbol: str
    option: OptionGreekSnapshot
    side: str  # "BUY" (this harness only simulates opening longs)
    qty: int
    note: str


@dataclass(frozen=True)
class OptionOrderIntent:
    ts_et: datetime
    symbol: str
    option_symbol: str
    side: str  # BUY/SELL
    qty: int
    limit_price: float
    rationale: str


@dataclass(frozen=True)
class RiskDecision:
    ts_et: datetime
    approved: bool
    action: str  # "ALLOW" / "BLOCK" / "ALLOW_REDUCED"
    reason: str
    adjusted_qty: int


@dataclass(frozen=True)
class SimulatedFill:
    ts_et: datetime
    filled: bool
    qty: int
    fill_price: Optional[float]
    note: str


@dataclass(frozen=True)
class ObserverExplanation:
    ts_et: datetime
    summary: str
    details: str


# -----------------------------
# Synthetic market data generator
# -----------------------------

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _round2(x: float) -> float:
    return float(f"{x:.2f}")


def _synthetic_iv(spot: float, strike: float, right: str) -> float:
    # Simple skew: puts higher IV than calls; further OTM slightly higher IV.
    moneyness = abs(strike / spot - 1.0)
    base = 0.14 + 0.25 * moneyness
    if right == "P":
        base += 0.03
    return _clamp(base, 0.08, 0.80)


def _synthetic_mid(spot: float, strike: float, right: str, iv: float, t_days: float) -> float:
    # Not a real model: monotone in intrinsic + “time value” ~ spot * iv * sqrt(t).
    intrinsic = max(0.0, spot - strike) if right == "C" else max(0.0, strike - spot)
    time_value = max(0.05, spot * iv * math.sqrt(max(t_days, 0.1) / 365.0) * 0.15)
    return max(0.01, intrinsic + time_value)


def _synthetic_greeks(spot: float, strike: float, right: str, iv: float) -> Tuple[float, float, float, float]:
    """
    Return (delta, gamma, vega, theta) – simplified and bounded.

    Gamma peaked near ATM. Delta is a smooth step.
    """

    x = (spot - strike) / max(1.0, 0.01 * spot)  # normalize by ~1% of spot
    # Delta: smooth; calls in [0,1], puts in [-1,0]
    call_delta = 1.0 / (1.0 + math.exp(-x))
    delta = call_delta if right == "C" else call_delta - 1.0
    # Gamma: bell-shaped around ATM
    gamma = math.exp(-(x * x) / 2.0) * (0.015 / max(spot, 1.0))
    # Vega: proportional to gamma * spot * sqrt(T) proxy
    vega = gamma * spot * 0.7
    # Theta: more negative with higher IV
    theta = -max(0.001, iv * 0.04)
    return (float(delta), float(gamma), float(vega), float(theta))


def _build_synthetic_chain(
    ts_et: datetime,
    spot: float,
    force_negative_gex: bool,
) -> Tuple[OptionGreekSnapshot, ...]:
    expiry = ts_et.date()  # 0DTE for simulation

    # Strikes around spot in $1 increments.
    atm = round(spot)
    strikes = [float(atm + k) for k in range(-5, 6)]
    snaps: list[OptionGreekSnapshot] = []

    # OI profile: puts heavier OI when negative GEX regime is forced.
    for strike in strikes:
        for right in ("C", "P"):
            iv = _synthetic_iv(spot, strike, right)
            delta, gamma, vega, theta = _synthetic_greeks(spot, strike, right, iv)
            mid = _synthetic_mid(spot, strike, right, iv, t_days=0.4)

            # Synthetic open interest: peaked near ATM.
            distance = abs(strike - spot)
            oi_base = int(2500 * math.exp(-(distance * distance) / 18.0) + random.randint(0, 150))
            if force_negative_gex:
                if right == "P":
                    oi_base = int(oi_base * 1.35)
                else:
                    oi_base = int(oi_base * 0.85)

            snaps.append(
                OptionGreekSnapshot(
                    expiry=expiry,
                    strike=strike,
                    right=right,
                    mid=_round2(mid),
                    delta=float(f"{delta:.3f}"),
                    gamma=float(f"{gamma:.6f}"),
                    vega=float(f"{vega:.6f}"),
                    theta=float(f"{theta:.6f}"),
                    iv=float(f"{iv:.3f}"),
                    open_interest=max(1, oi_base),
                )
            )

    return tuple(snaps)


def _compute_synthetic_gex(chain: Sequence[OptionGreekSnapshot], spot: float, force_negative_gex: bool) -> float:
    """
    Synthetic dealer GEX proxy.

    We do NOT claim economic realism; this is a *signal knob* to exercise the pipeline.
    """

    # Use gamma * OI * spot^2 scaling to get a large-ish number.
    raw = 0.0
    for o in chain:
        sign = -1.0 if o.right == "P" else 1.0  # puts contribute opposite sign (synthetic)
        raw += sign * o.gamma * o.open_interest * (spot * spot) * CONTRACT_MULTIPLIER

    if force_negative_gex:
        raw = -abs(raw)
    return float(raw)


def synthetic_market_stream(
    *,
    steps: int,
    start_ts_et: datetime,
    force_negative_gex: bool,
) -> Iterable[MarketEvent]:
    spot = 470.00
    prev_spot = spot

    # Light random walk. Add a small, time-of-day nudge to create variety.
    for i in range(steps):
        ts = start_ts_et + timedelta(minutes=i)
        tod = ts.hour + ts.minute / 60.0
        drift = 0.00
        if tod >= 15.5:  # late-day chop
            drift = -0.01
        vol = 0.25
        spot += random.gauss(drift, vol)
        spot = max(1.0, spot)

        chain = _build_synthetic_chain(ts, spot, force_negative_gex=force_negative_gex)
        gex = _compute_synthetic_gex(chain, spot, force_negative_gex=force_negative_gex)
        spot_change_1m = spot - prev_spot
        prev_spot = spot

        yield MarketEvent(
            ts_et=ts,
            symbol=SYMBOL,
            spot=_round2(spot),
            spot_change_1m=float(f"{spot_change_1m:.2f}"),
            gex=float(f"{gex:.2f}"),
            chain=chain,
        )


# -----------------------------
# Agents (simulation-only)
# -----------------------------

class GammaScalper:
    """
    Gamma scalper signal generator (simulation-only).
    """

    def on_market(self, evt: MarketEvent) -> GammaSignal:
        regime = "NEG_GEX" if evt.gex < 0 else "POS_GEX"
        # In negative GEX regimes, price tends to be “unstable”; we model it as trend bias.
        bias = "TREND" if regime == "NEG_GEX" else "MEAN_REVERT"

        # Strength reacts to |1m change| and |gex|.
        move = abs(evt.spot_change_1m)
        gex_mag = abs(evt.gex)
        strength = _clamp((move / 0.60) * 0.55 + (math.log10(1.0 + gex_mag) / 8.0) * 0.45, 0.0, 1.0)

        note = f"regime={regime} bias={bias} move_1m={evt.spot_change_1m:+.2f} gex={evt.gex:+.0f}"
        return GammaSignal(
            ts_et=evt.ts_et,
            symbol=evt.symbol,
            regime=regime,
            bias=bias,
            strength=float(f"{strength:.2f}"),
            note=note,
        )


class OptionContractSelector:
    """
    Chooses an option contract based on the gamma signal (simulation-only).
    """

    def pick(self, evt: MarketEvent, sig: GammaSignal) -> OptionContractChoice:
        # Direction choice:
        # - TREND: buy calls if price up, buy puts if price down
        # - MEAN_REVERT: fade the last 1m move
        if sig.bias == "TREND":
            right = "C" if evt.spot_change_1m >= 0 else "P"
        else:
            right = "P" if evt.spot_change_1m >= 0 else "C"

        # Pick near-ATM with slight OTM preference.
        target_strike = round(evt.spot) + (1.0 if right == "C" else -1.0)
        candidates = [o for o in evt.chain if o.right == right]
        chosen = min(candidates, key=lambda o: (abs(o.strike - target_strike), abs(o.delta - 0.45)))

        # Quantity scales with strength but remains small.
        qty = max(1, int(round(1 + 3 * sig.strength)))
        note = f"picked={chosen.symbol} strike={chosen.strike:.0f}{right} mid={chosen.mid:.2f} qty={qty}"
        return OptionContractChoice(
            ts_et=evt.ts_et,
            symbol=evt.symbol,
            option=chosen,
            side="BUY",
            qty=qty,
            note=note,
        )


class OptionsRiskEngine:
    """
    Risk gate (simulation-only).

    Rules to exercise:
    - Block new entries after 15:45 ET.
    - Cap position size.
    - Block if premium too high (proxy for wide risk).
    - Reduce size when GEX is negative and late-day.
    """

    def __init__(self) -> None:
        self.max_qty = 4
        self.max_premium = 8.00  # per-contract
        self.cutoff_time = time(15, 45)  # ET

    def assess(self, evt: MarketEvent, intent: OptionOrderIntent) -> RiskDecision:
        ts = evt.ts_et
        if ts.timetz().replace(tzinfo=None) >= self.cutoff_time:
            return RiskDecision(
                ts_et=ts,
                approved=False,
                action="BLOCK",
                reason="No new entries after 15:45 ET in simulation risk policy.",
                adjusted_qty=0,
            )

        if intent.qty > self.max_qty:
            return RiskDecision(
                ts_et=ts,
                approved=True,
                action="ALLOW_REDUCED",
                reason=f"Qty capped to {self.max_qty} by simulation risk policy.",
                adjusted_qty=self.max_qty,
            )

        if intent.limit_price > self.max_premium:
            return RiskDecision(
                ts_et=ts,
                approved=False,
                action="BLOCK",
                reason=f"Premium {intent.limit_price:.2f} too high (> {self.max_premium:.2f}) in simulation policy.",
                adjusted_qty=0,
            )

        # Mild late-day + negative-gex size reduction (pre-cutoff).
        adjusted = intent.qty
        if evt.gex < 0 and ts.hour == 15 and ts.minute >= 35:
            adjusted = max(1, int(math.floor(intent.qty * 0.5)))
            if adjusted != intent.qty:
                return RiskDecision(
                    ts_et=ts,
                    approved=True,
                    action="ALLOW_REDUCED",
                    reason="Negative GEX + late day: reduced size in simulation policy.",
                    adjusted_qty=adjusted,
                )

        return RiskDecision(
            ts_et=ts,
            approved=True,
            action="ALLOW",
            reason="Allowed by simulation risk policy.",
            adjusted_qty=adjusted,
        )


class ShadowOptionsExecutor:
    """
    Shadow executor (simulation-only).

    - Never sends orders anywhere.
    - Produces a simulated fill record for debugging and downstream testing.
    """

    def __init__(self, *, dry_run: bool) -> None:
        self.dry_run = dry_run

    def execute(self, intent: OptionOrderIntent, decision: RiskDecision) -> SimulatedFill:
        if not decision.approved or decision.adjusted_qty <= 0:
            return SimulatedFill(
                ts_et=intent.ts_et,
                filled=False,
                qty=0,
                fill_price=None,
                note="Not executed: blocked by risk.",
            )

        # Simulate “reasonable” fill: mid +/- small slippage.
        slip = random.uniform(-0.02, 0.04)  # $0.02 improvement to $0.04 worse
        fill = max(0.01, intent.limit_price + slip)
        fill = _round2(fill)

        if self.dry_run:
            note = f"DRY_RUN: would fill {decision.adjusted_qty} @ {fill:.2f} (simulated)"
        else:
            note = f"SIM_FILL: filled {decision.adjusted_qty} @ {fill:.2f} (simulated, no external calls)"

        return SimulatedFill(
            ts_et=intent.ts_et,
            filled=True,
            qty=decision.adjusted_qty,
            fill_price=fill,
            note=note,
        )


class Observer:
    """
    Observer / explainer agent (simulation-only).
    """

    def explain(
        self,
        evt: MarketEvent,
        sig: GammaSignal,
        choice: OptionContractChoice,
        intent: OptionOrderIntent,
        decision: RiskDecision,
        fill: SimulatedFill,
    ) -> ObserverExplanation:
        summary = (
            f"{evt.ts_et.strftime('%H:%M')} ET | spot={evt.spot:.2f} gex={evt.gex:+.0f} | "
            f"{sig.regime}/{sig.bias} s={sig.strength:.2f} | "
            f"intent={intent.side} {intent.qty} {intent.option_symbol} @ {intent.limit_price:.2f} | "
            f"risk={decision.action} | fill={'YES' if fill.filled else 'NO'}"
        )
        details = (
            f"- Market: spot_change_1m={evt.spot_change_1m:+.2f}\n"
            f"- Signal: {sig.note}\n"
            f"- Contract: {choice.note}\n"
            f"- Intent rationale: {intent.rationale}\n"
            f"- Risk: {decision.reason}\n"
            f"- Execution: {fill.note}"
        )
        return ObserverExplanation(ts_et=evt.ts_et, summary=summary, details=details)


# -----------------------------
# Pipeline wiring
# -----------------------------

def _intent_from_choice(choice: OptionContractChoice) -> OptionOrderIntent:
    # Limit price: mid + small “urgency” bump.
    limit = _round2(choice.option.mid + 0.03)
    rationale = (
        f"Simulation intent from GammaScalper; contract={choice.option.symbol} "
        f"delta={choice.option.delta:+.3f} gamma={choice.option.gamma:.6f} iv={choice.option.iv:.3f}"
    )
    return OptionOrderIntent(
        ts_et=choice.ts_et,
        symbol=choice.symbol,
        option_symbol=choice.option.symbol,
        side=choice.side,
        qty=choice.qty,
        limit_price=limit,
        rationale=rationale,
    )


def _parse_start_time(hhmm: str) -> time:
    try:
        parts = hhmm.strip().split(":")
        if len(parts) != 2:
            raise ValueError("Expected HH:MM")
        hh = int(parts[0])
        mm = int(parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError("Out of range")
        return time(hh, mm)
    except Exception as e:
        raise SystemExit(f"ERROR: invalid --start-time '{hhmm}'. Expected HH:MM. ({e})")


def run_simulation(*, steps: int, start_time_hhmm: str, force_negative_gex: bool, dry_run: bool) -> int:
    random.seed(7)  # deterministic-ish runs for debugging

    st = _parse_start_time(start_time_hhmm)
    start_ts_et = datetime.combine(date.today(), st, tzinfo=ET)

    gamma = GammaScalper()
    selector = OptionContractSelector()
    risk = OptionsRiskEngine()
    executor = ShadowOptionsExecutor(dry_run=dry_run)
    observer = Observer()

    cutoff = time(15, 45)
    crossed_cutoff = False

    print("=== Local SAFE agent simulation harness (TEST ONLY) ===")
    print(f"symbol={SYMBOL} steps={steps} start={start_ts_et.strftime('%H:%M')} ET dry_run={dry_run}")
    print(f"force_negative_gex={force_negative_gex}")
    print("SAFETY: network disabled; no broker/execution/firestore/db imports.\n")

    for evt in synthetic_market_stream(
        steps=steps,
        start_ts_et=start_ts_et,
        force_negative_gex=force_negative_gex,
    ):
        if (not crossed_cutoff) and evt.ts_et.timetz().replace(tzinfo=None) >= cutoff:
            crossed_cutoff = True
            print(f"\n--- TIME BOUNDARY: crossed 15:45 ET at {evt.ts_et.strftime('%H:%M')} ---\n")

        sig = gamma.on_market(evt)
        choice = selector.pick(evt, sig)
        intent = _intent_from_choice(choice)
        decision = risk.assess(evt, intent)
        fill = executor.execute(intent, decision)
        expl = observer.explain(evt, sig, choice, intent, decision, fill)

        # Output requirements:
        print(f"[OptionOrderIntent] {intent.ts_et.strftime('%H:%M')} {intent.side} x{intent.qty} {intent.option_symbol} "
              f"limit={intent.limit_price:.2f}")
        print(f"[RiskDecision]     {decision.action} approved={decision.approved} adjusted_qty={decision.adjusted_qty} "
              f"reason={decision.reason}")
        print(f"[SimFill]          filled={fill.filled} qty={fill.qty} price={fill.fill_price} note={fill.note}")
        print(f"[Observer]         {expl.summary}")
        print(expl.details)
        print("")

    print("=== Simulation complete ===")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="SAFE local multi-agent simulation harness (no broker/HTTP/Firestore/DB).",
    )
    parser.add_argument("--steps", type=int, default=20, help="Number of 1-minute steps to simulate.")
    parser.add_argument(
        "--start-time",
        type=str,
        default="15:40",
        help="Start time in ET, HH:MM (e.g. 15:40). Default crosses 15:45.",
    )
    parser.add_argument(
        "--force-negative-gex",
        action="store_true",
        help="Force negative dealer gamma exposure regime (exercise trend bias / risk reductions).",
    )

    dr = parser.add_mutually_exclusive_group()
    dr.add_argument("--dry-run", action="store_true", help="Do not 'execute'; only simulate fills (default).")
    dr.add_argument("--no-dry-run", action="store_true", help="Simulate fills (still no external calls).")

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.steps <= 0:
        raise SystemExit("ERROR: --steps must be > 0")

    # Default is dry-run.
    dry_run = True if (not args.no_dry_run) else False

    # Re-assert after arg parsing (defense-in-depth).
    _assert_forbidden_imports_absent()

    return run_simulation(
        steps=args.steps,
        start_time_hhmm=args.start_time,
        force_negative_gex=bool(args.force_negative_gex),
        dry_run=dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())

