"""
Guarded manual PAPER options order script (SPY only, single-leg only).

Safety intent:
- PAPER trading only (hard-refuse otherwise)
- SPY options only (hard-refuse any other underlying)
- Single-leg only (no legs / no multi-leg order_class)
- No strategy integration; no execution engine usage
- Fail-closed on missing guardrails or configuration
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import scripts.lib.exec_guard as exec_guard


_SPY_OPTION_SYMBOL_RE = re.compile(r"^SPY\d{6}[CP]\d{8}$")


def _require_env(name: str, *, expected: str | None = None) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        raise SystemExit(f"REFUSED: missing required environment variable: {name}")
    if expected is not None and v != expected:
        raise SystemExit(f"REFUSED: {name} must be {expected!r} (got {v!r})")
    return v


def _require_paper_alpaca_base_url() -> None:
    """
    Hard-reject any configured non-paper Alpaca trading URL.

    Note: `alpaca-py` uses `paper=True` to select its endpoint, but we still
    refuse a live base URL if configured to avoid accidental misconfiguration.
    """
    raw = (os.getenv("APCA_API_BASE_URL") or "").strip()
    if not raw:
        return

    p = urlparse(raw)
    host = (p.hostname or "").lower().strip()
    if host != "paper-api.alpaca.markets":
        raise SystemExit(
            "REFUSED: non-paper Alpaca base URL configured via APCA_API_BASE_URL. "
            f"Expected host 'paper-api.alpaca.markets', got {host!r} (raw={raw!r})"
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Place a single-leg SPY option market order on Alpaca PAPER (guarded)."
    )
    p.add_argument("--execution-confirm", required=True, help="Execution confirmation token (must match env).")
    p.add_argument("--contract-symbol", required=True, help="Alpaca/OCC option symbol (SPY only).")
    p.add_argument("--side", required=True, choices=["buy", "sell"], help="Order side.")
    p.add_argument("--qty", required=True, type=int, help="Contract quantity (positive integer).")
    return p.parse_args(argv)


def main() -> None:
    # Guard must be invoked exactly once per script.
    exec_guard.enforce_execution_policy(__file__, sys.argv)

    args = _parse_args(sys.argv[1:])

    if args.qty <= 0:
        raise SystemExit(f"REFUSED: --qty must be a positive integer (got {args.qty})")

    contract_symbol = str(args.contract_symbol).strip().upper()
    if not _SPY_OPTION_SYMBOL_RE.fullmatch(contract_symbol):
        raise SystemExit(
            "REFUSED: --contract-symbol must be a SPY option in expected format "
            "(e.g., SPY251230C00500000). "
            f"Got {contract_symbol!r}"
        )

    # Required safety gates (fail closed).
    _require_env("TRADING_MODE", expected="paper")
    _require_env("EXECUTION_ENABLED", expected="1")
    _require_env("EXECUTION_HALTED", expected="0")
    _require_env("EXEC_GUARD_UNLOCK", expected="1")

    confirm_env = _require_env("EXECUTION_CONFIRM_TOKEN")
    confirm_cli = str(args.execution_confirm).strip()
    if not confirm_cli:
        # argparse should prevent this, but keep fail-closed semantics explicit.
        raise SystemExit("REFUSED: missing required --execution-confirm token")
    if confirm_cli != confirm_env:
        raise SystemExit("REFUSED: --execution-confirm does not match EXECUTION_CONFIRM_TOKEN")

    _require_paper_alpaca_base_url()

    api_key = _require_env("APCA_API_KEY_ID")
    secret_key = _require_env("APCA_API_SECRET_KEY")

    print("=== Guarded PAPER SPY option order (single-leg) ===")
    print(f"- contract_symbol: {contract_symbol}")
    print(f"- side: {args.side}")
    print(f"- qty: {args.qty}")
    print("- order_type: market")
    print("- time_in_force: day")
    print("- alpaca_client: TradingClient(paper=True)")
    print("- safety: TRADING_MODE=paper, EXECUTION_ENABLED=1, EXECUTION_HALTED=0, EXEC_GUARD_UNLOCK=1, token matched")

    # Import Alpaca SDK only at runtime (keeps import-time side effects minimal).
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest

    trading_client = TradingClient(api_key, secret_key, paper=True)

    order_req = MarketOrderRequest(
        symbol=contract_symbol,
        qty=args.qty,
        side=OrderSide.BUY if args.side == "buy" else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        # Single-leg only: do not set `legs` or `order_class`.
    )

    print("=== Submitting order request ===")
    try:
        req_dump = order_req.model_dump()
    except Exception:
        req_dump = {"symbol": contract_symbol, "qty": args.qty, "side": args.side, "time_in_force": "day"}
    print(json.dumps(req_dump, indent=2, default=str, sort_keys=True))

    # Never swallow exceptions: let API and transport errors raise.
    resp = trading_client.submit_order(order_data=order_req)

    print("=== Alpaca response ===")
    try:
        print(json.dumps(resp.model_dump(), indent=2, default=str, sort_keys=True))
    except Exception:
        print(resp)


if __name__ == "__main__":
    main()

