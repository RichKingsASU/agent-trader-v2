from __future__ import annotations

from backend.contracts.risk import RiskCheckResult, TradeCheckRequest
from backend.risk_service import models as risk_models


def test_risk_trade_check_contract_is_shared_and_strict() -> None:
    """
    Contract gate:
    - All producers/consumers import the same request/response models
    - The models reject unknown fields (no implicit cross-service assumptions)
    """

    assert risk_models.TradeCheckRequest is TradeCheckRequest
    assert risk_models.RiskCheckResult is RiskCheckResult

    req = TradeCheckRequest.model_validate(
        {
            "broker_account_id": "00000000-0000-0000-0000-000000000001",
            "strategy_id": "00000000-0000-0000-0000-000000000002",
            "symbol": "SPY",
            "notional": "1000.00",
            "side": "buy",
            "current_open_positions": 0,
            "current_trades_today": 0,
            "current_day_loss": "0.0",
            "current_day_drawdown": "0.0",
        }
    )
    assert req.symbol == "SPY"

    # Unknown fields must be rejected (prevents “I thought you accepted X” drift).
    try:
        TradeCheckRequest.model_validate({**req.model_dump(mode="json"), "extra": "nope"})
        raise AssertionError("Expected extra fields to be rejected")
    except Exception:
        pass

    res = RiskCheckResult.model_validate({"allowed": True, "reason": None, "scope": None})
    assert res.allowed is True

    try:
        RiskCheckResult.model_validate({"allowed": True, "scope": None, "unknown": "nope"})
        raise AssertionError("Expected extra fields to be rejected")
    except Exception:
        pass

