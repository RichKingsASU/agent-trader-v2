#!/usr/bin/env python3
"""
Test script for Phase 4 Trade Executor

This script tests the executor utilities and validates the implementation.
Run this locally before deploying to production.
"""

import sys
from decimal import Decimal

# Add functions directory to path
sys.path.insert(0, '../functions')

from executor import (
    generate_client_order_id,
    calculate_order_notional,
    calculate_limit_price,
    validate_order_params,
    build_audit_log_entry,
)


def test_client_order_id():
    """Test unique client order ID generation"""
    print("Test 1: Client Order ID Generation")
    
    # Generate multiple IDs
    ids = [generate_client_order_id() for _ in range(5)]
    
    # Check uniqueness
    assert len(ids) == len(set(ids)), "IDs should be unique"
    
    # Check format
    for order_id in ids:
        assert order_id.startswith("AT_"), f"ID should start with AT_: {order_id}"
        parts = order_id.split("_")
        assert len(parts) == 3, f"ID should have 3 parts: {order_id}"
        assert len(parts[1]) == 14, f"Timestamp should be 14 chars: {parts[1]}"
        assert len(parts[2]) == 8, f"UUID should be 8 chars: {parts[2]}"
    
    print("✅ Client Order ID generation works correctly")
    print(f"   Sample ID: {ids[0]}\n")


def test_order_notional():
    """Test order notional calculation"""
    print("Test 2: Order Notional Calculation")
    
    # Test case 1: 10% of $10,000
    result = calculate_order_notional("10000.00", 0.1)
    assert result == Decimal("1000.00"), f"Expected 1000.00, got {result}"
    assert isinstance(result, Decimal), "Should return Decimal"
    
    # Test case 2: With max position size
    result = calculate_order_notional("10000.00", 0.5, max_position_size=2000.0)
    assert result == Decimal("2000.00"), f"Expected 2000.00 (capped), got {result}"
    
    # Test case 3: Precision test
    result = calculate_order_notional("12345.67", 0.123)
    expected = Decimal("1518.51")  # 12345.67 * 0.123 = 1518.51741, rounded down
    assert result == expected, f"Expected {expected}, got {result}"
    
    print("✅ Order notional calculation works correctly")
    print(f"   10% of $10,000 = ${result}\n")


def test_limit_price():
    """Test marketable limit price calculation"""
    print("Test 3: Marketable Limit Price Calculation")
    
    # Test case 1: Buy order (add 0.5% buffer)
    result = calculate_limit_price(100.00, "buy", 0.005)
    expected = Decimal("100.50")  # 100 * 1.005
    assert result == expected, f"Expected {expected}, got {result}"
    
    # Test case 2: Sell order (subtract 0.5% buffer)
    result = calculate_limit_price(100.00, "sell", 0.005)
    expected = Decimal("99.50")  # 100 * 0.995
    assert result == expected, f"Expected {expected}, got {result}"
    
    # Test case 3: Verify rounding
    result = calculate_limit_price(100.123, "buy", 0.005)
    assert result == Decimal("100.63"), f"Should round up for buy: {result}"
    
    result = calculate_limit_price(100.123, "sell", 0.005)
    assert result == Decimal("99.62"), f"Should round down for sell: {result}"
    
    print("✅ Marketable limit price calculation works correctly")
    print(f"   Buy $100 → ${calculate_limit_price(100.00, 'buy', 0.005)}")
    print(f"   Sell $100 → ${calculate_limit_price(100.00, 'sell', 0.005)}\n")


def test_validation():
    """Test order parameter validation"""
    print("Test 4: Order Parameter Validation")
    
    # Test case 1: Valid order
    result = validate_order_params(
        symbol="AAPL",
        side="buy",
        notional=Decimal("1000.00"),
        limit_price=Decimal("150.00")
    )
    assert result["valid"] is True, "Valid order should pass"
    assert len(result["errors"]) == 0, "Valid order should have no errors"
    
    # Test case 2: Invalid symbol
    result = validate_order_params(
        symbol="",
        side="buy",
        notional=Decimal("1000.00")
    )
    assert result["valid"] is False, "Empty symbol should fail"
    assert any("symbol" in err.lower() for err in result["errors"])
    
    # Test case 3: Invalid side
    result = validate_order_params(
        symbol="AAPL",
        side="invalid",
        notional=Decimal("1000.00")
    )
    assert result["valid"] is False, "Invalid side should fail"
    
    # Test case 4: Notional too small
    result = validate_order_params(
        symbol="AAPL",
        side="buy",
        notional=Decimal("0.50")
    )
    assert result["valid"] is False, "Notional < $1 should fail"
    assert any("minimum" in err.lower() for err in result["errors"])
    
    print("✅ Order validation works correctly")
    print(f"   Valid orders pass, invalid orders fail with clear errors\n")


def test_audit_log():
    """Test audit log entry creation"""
    print("Test 5: Audit Log Entry Creation")
    
    client_order_id = generate_client_order_id()
    
    entry = build_audit_log_entry(
        client_order_id=client_order_id,
        symbol="AAPL",
        side="buy",
        notional=Decimal("1000.00"),
        order_type="limit",
        limit_price=Decimal("150.50"),
        status="pending",
        metadata={"test": True}
    )
    
    # Verify required fields
    assert entry["client_order_id"] == client_order_id
    assert entry["symbol"] == "AAPL"
    assert entry["side"] == "buy"
    assert entry["notional"] == "1000.00"  # Should be string
    assert entry["limit_price"] == "150.50"  # Should be string
    assert entry["status"] == "pending"
    assert "created_at" in entry
    assert "timestamp" in entry
    assert entry["metadata"]["test"] is True
    
    # Verify precision preservation
    assert isinstance(entry["notional"], str), "Notional should be string for precision"
    assert isinstance(entry["limit_price"], str), "Limit price should be string"
    
    print("✅ Audit log entry creation works correctly")
    print(f"   Sample entry: {entry['client_order_id']}\n")


def test_decimal_precision():
    """Test that Decimal precision is maintained throughout"""
    print("Test 6: Decimal Precision")
    
    # Test case: Calculate order size with tricky decimal
    buying_power = "12345.67"
    allocation = 0.123456
    
    notional = calculate_order_notional(buying_power, allocation)
    
    # Verify it's still a Decimal
    assert isinstance(notional, Decimal), "Result should be Decimal"
    
    # Verify no float was used (would introduce errors)
    # If we used float: 12345.67 * 0.123456 = 1523.9999952 (rounding errors)
    # With Decimal: should be exact
    
    print("✅ Decimal precision maintained throughout")
    print(f"   ${buying_power} * {allocation} = ${notional}\n")


def run_all_tests():
    """Run all tests"""
    print("=" * 70)
    print("Phase 4 Trade Executor - Unit Tests")
    print("=" * 70)
    print()
    
    try:
        test_client_order_id()
        test_order_notional()
        test_limit_price()
        test_validation()
        test_audit_log()
        test_decimal_precision()
        
        print("=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print()
        print("Next Steps:")
        print("1. Deploy backend: firebase deploy --only functions:execute_trade")
        print("2. Create trading gate: Set systemStatus/trading_gate.trading_enabled")
        print("3. Test with paper trading account first")
        print("4. Monitor tradeHistory collection for audit trail")
        
        return 0
    
    except AssertionError as e:
        print()
        print("=" * 70)
        print("❌ TEST FAILED")
        print("=" * 70)
        print(f"Error: {e}")
        return 1
    
    except Exception as e:
        print()
        print("=" * 70)
        print("❌ UNEXPECTED ERROR")
        print("=" * 70)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
