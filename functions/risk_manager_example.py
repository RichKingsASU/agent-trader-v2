#!/usr/bin/env python3
"""
Example usage of the Risk Manager kill-switch logic.

This script demonstrates how to use the risk manager to validate trades
before execution.
"""

import logging
from datetime import datetime, timezone

from risk_manager import (
    AccountSnapshot,
    TradeRequest,
    validate_trade_risk,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_1_valid_trade():
    """
    Example 1: Valid trade that should pass all checks.
    """
    logger.info("=" * 60)
    logger.info("EXAMPLE 1: Valid Trade")
    logger.info("=" * 60)
    
    # Account state
    account = AccountSnapshot(
        equity=95000.0,      # 5% below HWM (within 10% limit)
        buying_power=50000.0,
        cash=25000.0
    )
    
    # Trade request: $2,000 (4% of buying power, within 5% limit)
    trade = TradeRequest(
        symbol="AAPL",
        side="buy",
        qty=100,
        notional_usd=2000.0
    )
    
    logger.info(f"Account: Equity=${account.equity:,.2f}, Buying Power=${account.buying_power:,.2f}")
    logger.info(f"Trade: {trade.side.upper()} {trade.qty} shares of {trade.symbol} for ${trade.notional_usd:,.2f}")
    logger.info(f"Trade size: {(trade.notional_usd / account.buying_power * 100):.2f}% of buying power")
    
    # Validate trade (HWM will be fetched from Firestore if available)
    result = validate_trade_risk(account, trade)
    
    if result.allowed:
        logger.info("✅ RESULT: Trade ALLOWED - Validation passed")
    else:
        logger.error(f"❌ RESULT: Trade REJECTED - {result.reason}")
    
    return result


def example_2_hwm_violation():
    """
    Example 2: Trade rejected due to High Water Mark violation.
    """
    logger.info("\n" + "=" * 60)
    logger.info("EXAMPLE 2: High Water Mark Violation")
    logger.info("=" * 60)
    
    # Account state: equity 15% below HWM (exceeds 10% limit)
    account = AccountSnapshot(
        equity=85000.0,      # 15% below HWM (exceeds 10% limit)
        buying_power=50000.0,
        cash=25000.0
    )
    
    # Even a small trade should be rejected
    trade = TradeRequest(
        symbol="MSFT",
        side="buy",
        qty=50,
        notional_usd=1000.0
    )
    
    logger.info(f"Account: Equity=${account.equity:,.2f}, Buying Power=${account.buying_power:,.2f}")
    logger.info(f"Trade: {trade.side.upper()} {trade.qty} shares of {trade.symbol} for ${trade.notional_usd:,.2f}")
    logger.info("Note: Assuming HWM is $100,000 (equity is 15% below)")
    
    result = validate_trade_risk(account, trade)
    
    if result.allowed:
        logger.info("✅ RESULT: Trade ALLOWED")
    else:
        logger.error(f"❌ RESULT: Trade REJECTED - {result.reason}")
    
    return result


def example_3_oversized_trade():
    """
    Example 3: Trade rejected due to excessive size.
    """
    logger.info("\n" + "=" * 60)
    logger.info("EXAMPLE 3: Oversized Trade")
    logger.info("=" * 60)
    
    # Account state: healthy equity
    account = AccountSnapshot(
        equity=95000.0,
        buying_power=50000.0,
        cash=25000.0
    )
    
    # Large trade: $5,000 (10% of buying power, exceeds 5% limit)
    trade = TradeRequest(
        symbol="TSLA",
        side="buy",
        qty=200,
        notional_usd=5000.0
    )
    
    logger.info(f"Account: Equity=${account.equity:,.2f}, Buying Power=${account.buying_power:,.2f}")
    logger.info(f"Trade: {trade.side.upper()} {trade.qty} shares of {trade.symbol} for ${trade.notional_usd:,.2f}")
    logger.info(f"Trade size: {(trade.notional_usd / account.buying_power * 100):.2f}% of buying power (exceeds 5% limit)")
    
    result = validate_trade_risk(account, trade)
    
    if result.allowed:
        logger.info("✅ RESULT: Trade ALLOWED")
    else:
        logger.error(f"❌ RESULT: Trade REJECTED - {result.reason}")
    
    return result


def example_4_both_violations():
    """
    Example 4: Trade violates both HWM and size limits.
    """
    logger.info("\n" + "=" * 60)
    logger.info("EXAMPLE 4: Multiple Violations")
    logger.info("=" * 60)
    
    # Account state: equity well below HWM
    account = AccountSnapshot(
        equity=80000.0,      # 20% below HWM
        buying_power=50000.0,
        cash=25000.0
    )
    
    # Large trade
    trade = TradeRequest(
        symbol="NVDA",
        side="buy",
        qty=500,
        notional_usd=10000.0  # 20% of buying power
    )
    
    logger.info(f"Account: Equity=${account.equity:,.2f}, Buying Power=${account.buying_power:,.2f}")
    logger.info(f"Trade: {trade.side.upper()} {trade.qty} shares of {trade.symbol} for ${trade.notional_usd:,.2f}")
    logger.info(f"Trade size: {(trade.notional_usd / account.buying_power * 100):.2f}% of buying power")
    logger.info("Note: Both HWM and size limits violated")
    
    result = validate_trade_risk(account, trade)
    
    if result.allowed:
        logger.info("✅ RESULT: Trade ALLOWED")
    else:
        logger.error(f"❌ RESULT: Trade REJECTED - {result.reason}")
    
    return result


def example_5_edge_case_exactly_at_limits():
    """
    Example 5: Trade exactly at the safety limits (should pass).
    """
    logger.info("\n" + "=" * 60)
    logger.info("EXAMPLE 5: Exactly at Limits (Edge Case)")
    logger.info("=" * 60)
    
    # Account state: equity exactly at 90% of HWM
    account = AccountSnapshot(
        equity=90000.0,      # Exactly at 10% drawdown threshold
        buying_power=50000.0,
        cash=25000.0
    )
    
    # Trade exactly at 5% of buying power
    trade = TradeRequest(
        symbol="SPY",
        side="buy",
        qty=100,
        notional_usd=2500.0  # Exactly 5% of buying power
    )
    
    logger.info(f"Account: Equity=${account.equity:,.2f}, Buying Power=${account.buying_power:,.2f}")
    logger.info(f"Trade: {trade.side.upper()} {trade.qty} shares of {trade.symbol} for ${trade.notional_usd:,.2f}")
    logger.info(f"Trade size: {(trade.notional_usd / account.buying_power * 100):.2f}% of buying power (exactly at 5% limit)")
    logger.info("Note: Both at exact limits - should pass")
    
    result = validate_trade_risk(account, trade)
    
    if result.allowed:
        logger.info("✅ RESULT: Trade ALLOWED - At limits but within acceptable range")
    else:
        logger.error(f"❌ RESULT: Trade REJECTED - {result.reason}")
    
    return result


def example_6_sell_order():
    """
    Example 6: Sell order validation (same rules apply).
    """
    logger.info("\n" + "=" * 60)
    logger.info("EXAMPLE 6: Sell Order")
    logger.info("=" * 60)
    
    # Account state
    account = AccountSnapshot(
        equity=95000.0,
        buying_power=50000.0,
        cash=25000.0
    )
    
    # Sell order
    trade = TradeRequest(
        symbol="GOOGL",
        side="sell",
        qty=50,
        notional_usd=1500.0
    )
    
    logger.info(f"Account: Equity=${account.equity:,.2f}, Buying Power=${account.buying_power:,.2f}")
    logger.info(f"Trade: {trade.side.upper()} {trade.qty} shares of {trade.symbol} for ${trade.notional_usd:,.2f}")
    logger.info(f"Trade size: {(trade.notional_usd / account.buying_power * 100):.2f}% of buying power")
    
    result = validate_trade_risk(account, trade)
    
    if result.allowed:
        logger.info("✅ RESULT: Trade ALLOWED")
    else:
        logger.error(f"❌ RESULT: Trade REJECTED - {result.reason}")
    
    return result


def main():
    """
    Run all examples.
    """
    logger.info("\n" + "=" * 60)
    logger.info("RISK MANAGER EXAMPLES")
    logger.info("=" * 60)
    logger.info("Demonstrating various trade validation scenarios")
    logger.info("Note: These examples mock Firestore data (HWM assumed at $100,000)")
    logger.info("")
    
    examples = [
        ("Valid Trade", example_1_valid_trade),
        ("HWM Violation", example_2_hwm_violation),
        ("Oversized Trade", example_3_oversized_trade),
        ("Multiple Violations", example_4_both_violations),
        ("Edge Case (At Limits)", example_5_edge_case_exactly_at_limits),
        ("Sell Order", example_6_sell_order),
    ]
    
    results = []
    for name, func in examples:
        try:
            result = func()
            results.append((name, result.allowed))
        except Exception as e:
            logger.exception(f"Error running example '{name}': {e}")
            results.append((name, False))
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    for name, allowed in results:
        status = "✅ ALLOWED" if allowed else "❌ REJECTED"
        logger.info(f"{name:30s} {status}")
    
    logger.info("\n" + "=" * 60)
    logger.info("IMPORTANT NOTES")
    logger.info("=" * 60)
    logger.info("• High Water Mark must be set in Firestore at: riskManagement/highWaterMark")
    logger.info("• If HWM is not set, only trade size checks will be enforced")
    logger.info("• Update HWM regularly when account reaches new equity highs")
    logger.info("• These examples assume HWM is set to $100,000")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
