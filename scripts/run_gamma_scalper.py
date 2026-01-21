import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo
 
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
 
import scripts.lib.exec_guard as exec_guard
 
import alpaca_trade_api as tradeapi
import yfinance as yf
 
from backend.common.env import assert_paper_alpaca_base_url
from backend.common.kill_switch import ExecutionHaltedError, get_kill_switch_state, require_live_mode
 
 
DELTA_THRESHOLD = 0.15
STOP_LOSS_PERCENTAGE = 0.20
EXIT_TIME_ET = dt.time(15, 45)
ET = ZoneInfo("America/New_York")
 
 
def _require_gamma_scalper_execution_gate(*, execution_confirm: str) -> None:
    """
    Hard gate: refuse to place/close broker orders unless ALL conditions hold:
    - TRADING_MODE=paper
    - EXECUTION_HALTED=0 (explicitly)
    - global kill switch is NOT enabled (env/file)
    - EXEC_GUARD_UNLOCK=1
    - EXECUTION_CONFIRM_TOKEN matches --execution-confirm
    """
    trading_mode = str(os.getenv("TRADING_MODE") or "").strip().lower()
    if trading_mode != "paper":
        raise RuntimeError(f"REFUSED: TRADING_MODE must be 'paper' (got {trading_mode!r}).")
 
    halted_raw = str(os.getenv("EXECUTION_HALTED") or "").strip()
    if halted_raw != "0":
        raise RuntimeError(
            "REFUSED: EXECUTION_HALTED must be explicitly set to '0' to allow broker actions "
            f"(got {halted_raw!r})."
        )
 
    # Global kill switch (env/file). Fail-closed on evaluation errors.
    try:
        require_live_mode(operation="gamma_scalper broker action")
    except ExecutionHaltedError as e:
        raise RuntimeError(f"REFUSED: {e}") from e
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"REFUSED: could not evaluate kill switch: {e}") from e
 
    # Redundant with exec_guard MUST_LOCK, but required by audit contract at the broker boundary.
    if str(os.getenv("EXEC_GUARD_UNLOCK") or "").strip() != "1":
        raise RuntimeError("REFUSED: EXEC_GUARD_UNLOCK must be '1' to allow broker actions.")
 
    expected = (os.getenv("EXECUTION_CONFIRM_TOKEN") or "").strip()
    if not expected:
        raise RuntimeError("REFUSED: missing EXECUTION_CONFIRM_TOKEN (required for any order placement).")
    if str(execution_confirm).strip() != expected:
        raise RuntimeError("REFUSED: EXECUTION_CONFIRM mismatch (token did not match EXECUTION_CONFIRM_TOKEN).")
 
 
def _check_kill_switch_preflight() -> None:
    """
    Quick read-only check used for logging/debug; fail-closed.
    """
    enabled, source = get_kill_switch_state()
    if enabled:
        raise RuntimeError(f"REFUSED: kill switch enabled ({source or 'unknown'}).")
 
 
def _get_api() -> tradeapi.REST:
    api_key = (os.getenv("APCA_API_KEY_ID") or "").strip()
    api_secret = (os.getenv("APCA_API_SECRET_KEY") or "").strip()
    base_url = (os.getenv("APCA_API_BASE_URL") or "https://paper-api.alpaca.markets").strip()
    base_url = assert_paper_alpaca_base_url(base_url)
 
    if not api_key or not api_secret:
        raise RuntimeError("ERROR: APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set.")
 
    return tradeapi.REST(api_key, api_secret, base_url=base_url, api_version="v2")
 
 
def get_spy_200_sma() -> float:
    spy = yf.Ticker("SPY")
    hist = spy.history(period="220d")
    return float(hist["Close"].rolling(window=200).mean().iloc[-1])
 
 
def regime_filter() -> bool:
    spy_price = float(yf.Ticker("SPY").history(period="1d")["Close"].iloc[-1])
    sma_200 = get_spy_200_sma()
    return spy_price > sma_200
 
 
def get_portfolio_delta() -> float:
    # Placeholder example delta.
    return 0.10
 
 
def get_portfolio_vanna() -> float:
    return 0.02
 
 
def get_portfolio_charm() -> float:
    return -0.01
 
 
def rebalance_portfolio(delta: float) -> None:
    print(f"Current Delta: {delta}. Rebalancing portfolio to be delta-neutral.")
    # Placeholder: broker actions must be guarded at call sites.
 
 
def check_stop_loss(*, api: tradeapi.REST, execution_confirm: str) -> None:
    _require_gamma_scalper_execution_gate(execution_confirm=execution_confirm)
 
    account = api.get_account()
    initial_value = float(account.last_equity)
    current_value = float(account.equity)
    drawdown = (initial_value - current_value) / initial_value
    if drawdown >= STOP_LOSS_PERCENTAGE:
        print(f"Stop-loss of {STOP_LOSS_PERCENTAGE * 100}% hit. Liquidating positions.")
        api.close_all_positions()
 
 
def run(*, execution_confirm: str) -> int:
    # Preflight kill switch check (fail-closed) before we even build a broker client.
    _check_kill_switch_preflight()
 
    # Hard gate before any broker-capable initialization.
    _require_gamma_scalper_execution_gate(execution_confirm=execution_confirm)
    api = _get_api()
 
    print("Starting 0DTE Gamma Scalper Strategy (execution-capable; paper-only)...")
 
    if not regime_filter():
        print("Regime filter not met (SPY is not above 200-day SMA). Exiting.")
        return 0
 
    while True:
        now_et = dt.datetime.now(tz=ET).time()
 
        if now_et >= EXIT_TIME_ET:
            _require_gamma_scalper_execution_gate(execution_confirm=execution_confirm)
            print(f"Exit time of {EXIT_TIME_ET} reached. Liquidating positions.")
            api.close_all_positions()
            break
 
        check_stop_loss(api=api, execution_confirm=execution_confirm)
 
        portfolio_delta = get_portfolio_delta()
        vanna_adjustment = get_portfolio_vanna()
        charm_adjustment = get_portfolio_charm()
 
        adjusted_delta = portfolio_delta + vanna_adjustment + charm_adjustment
 
        if abs(adjusted_delta) > DELTA_THRESHOLD:
            # Placeholder; no broker actions here yet.
            rebalance_portfolio(adjusted_delta)
 
        time.sleep(60)
 
    return 0
 
 
def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run the 0DTE Gamma Scalper (paper-only; execution gated)."
    )
    parser.add_argument(
        "--execution-confirm",
        required=True,
        help="Required safety confirmation token (must match EXECUTION_CONFIRM_TOKEN).",
    )
    args = parser.parse_args(argv[1:])
    try:
        return run(execution_confirm=str(args.execution_confirm))
    except Exception as e:
        print(str(e))
        return 2
 
 
if __name__ == "__main__":
    exec_guard.enforce_execution_policy(__file__, sys.argv)
    raise SystemExit(main(sys.argv))
