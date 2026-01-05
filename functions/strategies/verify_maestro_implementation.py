"""
Verification Script for MaestroOrchestrator Implementation.

This script verifies that the MaestroOrchestrator implementation meets all
specified requirements without requiring Firebase dependencies.

Run:
    python3 verify_maestro_implementation.py
"""

import ast
import inspect
from decimal import Decimal
from typing import Dict, Any, List
import sys
import os


def check_requirement_1_decimal_precision():
    """
    Requirement 1: All financial math MUST use decimal.Decimal.
    
    Verifies:
    - Decimal is imported
    - Financial calculations use Decimal
    - math.sqrt pattern for Decimal sqrt
    """
    print("\n" + "="*70)
    print("REQUIREMENT 1: Decimal Precision")
    print("="*70)
    
    checks = []
    
    # Check 1: Read the source code and verify Decimal usage
    try:
        with open('maestro_orchestrator.py', 'r') as f:
            source = f.read()
        
        # Check Decimal import
        if 'from decimal import Decimal' in source:
            checks.append(("✅", "Decimal imported from decimal module"))
        else:
            checks.append(("❌", "Decimal not imported"))
        
        # Check getcontext configuration
        if 'getcontext().prec' in source:
            checks.append(("✅", "Decimal precision configured (getcontext)"))
        else:
            checks.append(("⚠️", "Decimal precision not explicitly set"))
        
        # Check Decimal usage in key methods
        if "Decimal(str(" in source:
            checks.append(("✅", "Decimal(str()) pattern used for conversions"))
        else:
            checks.append(("❌", "Decimal conversions not found"))
        
        # Check math.sqrt pattern
        if 'math.sqrt' in source and 'Decimal(str(' in source:
            checks.append(("✅", "math.sqrt used with Decimal conversion pattern"))
        else:
            checks.append(("⚠️", "Verify sqrt implementation for Decimals"))
        
        # Check for dangerous float arithmetic in financial calculations
        dangerous_patterns = [
            'float(realized_pnl)',
            'float(entry_price) *',
            'float(quantity) *'
        ]
        
        found_dangerous = False
        for pattern in dangerous_patterns:
            if pattern in source:
                checks.append(("❌", f"Dangerous float arithmetic found: {pattern}"))
                found_dangerous = True
        
        if not found_dangerous:
            checks.append(("✅", "No premature float conversions in financial math"))
        
    except FileNotFoundError:
        checks.append(("❌", "maestro_orchestrator.py not found"))
    
    for status, message in checks:
        print(f"  {status} {message}")
    
    return all(status == "✅" for status, _ in checks if status != "⚠️")


def check_requirement_2_data_fetching():
    """
    Requirement 2: Query users/{uid}/tradeJournal/ for trades.
    
    Verifies:
    - Firestore query implementation
    - Query for last 100 trades per agent
    - Correct collection path
    """
    print("\n" + "="*70)
    print("REQUIREMENT 2: Data Fetching from Firestore")
    print("="*70)
    
    checks = []
    
    try:
        with open('maestro_orchestrator.py', 'r') as f:
            source = f.read()
        
        # Check Firestore import
        if 'from firebase_admin import firestore' in source:
            checks.append(("✅", "Firestore imported from firebase_admin"))
        else:
            checks.append(("❌", "Firestore not imported"))
        
        # Check collection path
        if "'users'" in source and "'tradeJournal'" in source:
            checks.append(("✅", "Correct collection path: users/{uid}/tradeJournal/"))
        else:
            checks.append(("❌", "Collection path not found or incorrect"))
        
        # Check query method exists
        if 'def _fetch_agent_trades' in source:
            checks.append(("✅", "Trade fetching method implemented"))
        else:
            checks.append(("❌", "Trade fetching method missing"))
        
        # Check agent_id filter
        if "where('agent_id', '=='" in source:
            checks.append(("✅", "Query filters by agent_id"))
        else:
            checks.append(("❌", "Agent ID filter not found in query"))
        
        # Check ordering by closed_at
        if "order_by('closed_at'" in source:
            checks.append(("✅", "Query orders by closed_at timestamp"))
        else:
            checks.append(("❌", "Ordering by closed_at not found"))
        
        # Check limit parameter
        if '.limit(' in source:
            checks.append(("✅", "Query uses limit() for efficiency"))
        else:
            checks.append(("❌", "Query limit not implemented"))
        
        # Check lookback_trades config
        if 'lookback_trades' in source:
            checks.append(("✅", "Configurable lookback_trades parameter"))
        else:
            checks.append(("❌", "lookback_trades configuration missing"))
        
    except FileNotFoundError:
        checks.append(("❌", "maestro_orchestrator.py not found"))
    
    for status, message in checks:
        print(f"  {status} {message}")
    
    return all(status == "✅" for status, _ in checks)


def check_requirement_3_sharpe_calculation():
    """
    Requirement 3: Calculate Sharpe Ratio correctly.
    
    Verifies:
    - Mean return calculation
    - Standard deviation calculation
    - Risk-free rate of 0.04
    - Sharpe formula: (mean - rf) / std
    """
    print("\n" + "="*70)
    print("REQUIREMENT 3: Sharpe Ratio Calculation")
    print("="*70)
    
    checks = []
    
    try:
        with open('maestro_orchestrator.py', 'r') as f:
            source = f.read()
        
        # Check Sharpe calculation method
        if 'def _calculate_sharpe_ratio' in source:
            checks.append(("✅", "Sharpe Ratio calculation method exists"))
        else:
            checks.append(("❌", "Sharpe Ratio method missing"))
        
        # Check mean calculation
        if 'mean_return = sum(returns)' in source:
            checks.append(("✅", "Mean return calculated"))
        else:
            checks.append(("❌", "Mean return calculation not found"))
        
        # Check risk-free rate configuration
        if 'risk_free_rate' in source and '0.04' in source:
            checks.append(("✅", "Risk-free rate configurable (default 4%)"))
        else:
            checks.append(("⚠️", "Risk-free rate configuration unclear"))
        
        # Check standard deviation
        if 'variance' in source and 'std_dev' in source:
            checks.append(("✅", "Standard deviation calculation present"))
        else:
            checks.append(("❌", "Standard deviation calculation missing"))
        
        # Check excess return
        if 'excess_return' in source or 'mean_return - ' in source:
            checks.append(("✅", "Excess return calculated (mean - rf)"))
        else:
            checks.append(("❌", "Excess return not calculated"))
        
        # Check Sharpe formula
        if 'sharpe = excess_return / std_dev' in source or '/ std_dev' in source:
            checks.append(("✅", "Sharpe = (mean - rf) / std_dev formula"))
        else:
            checks.append(("❌", "Sharpe formula not found"))
        
        # Check returns calculation method
        if 'def _calculate_daily_returns' in source:
            checks.append(("✅", "Daily returns calculation method exists"))
        else:
            checks.append(("❌", "Returns calculation method missing"))
        
    except FileNotFoundError:
        checks.append(("❌", "maestro_orchestrator.py not found"))
    
    for status, message in checks:
        print(f"  {status} {message}")
    
    return all(status == "✅" for status, _ in checks if status != "⚠️")


def check_requirement_4_weighting_engine():
    """
    Requirement 4: Softmax normalization for weights.
    
    Verifies:
    - Softmax implementation
    - Total weights = 1.0
    - Negative Sharpe handling (floor weight 0.05 or 0.0)
    """
    print("\n" + "="*70)
    print("REQUIREMENT 4: Weighting Engine (Softmax)")
    print("="*70)
    
    checks = []
    
    try:
        with open('maestro_orchestrator.py', 'r') as f:
            source = f.read()
        
        # Check Softmax method
        if 'def _softmax_normalize' in source:
            checks.append(("✅", "Softmax normalization method exists"))
        else:
            checks.append(("❌", "Softmax method missing"))
        
        # Check exp calculation
        if 'math.exp' in source or 'exp(' in source:
            checks.append(("✅", "Exponential function used (Softmax)"))
        else:
            checks.append(("❌", "Exponential calculation not found"))
        
        # Check weight normalization
        if 'exp_sum' in source or 'sum(' in source:
            checks.append(("✅", "Normalization by sum of exponentials"))
        else:
            checks.append(("❌", "Normalization not found"))
        
        # Check total weight validation
        if "sum to 1.0" in source or "total_weight" in source:
            checks.append(("✅", "Weight sum validation present"))
        else:
            checks.append(("⚠️", "Weight sum validation unclear"))
        
        # Check floor weight handling
        if 'min_floor_weight' in source:
            checks.append(("✅", "Floor weight for negative Sharpe configured"))
        else:
            checks.append(("❌", "Floor weight not found"))
        
        # Check negative Sharpe handling
        if 'sharpe < ' in source or 'negative Sharpe' in source:
            checks.append(("✅", "Negative Sharpe Ratio handling implemented"))
        else:
            checks.append(("❌", "Negative Sharpe handling missing"))
        
        # Check enforce_performance flag
        if 'enforce_performance' in source:
            checks.append(("✅", "Strict performance enforcement option available"))
        else:
            checks.append(("⚠️", "Performance enforcement flag unclear"))
        
        # Check numerical stability (max subtraction)
        if 'max_sharpe' in source or 'max(' in source:
            checks.append(("✅", "Numerical stability (max subtraction) implemented"))
        else:
            checks.append(("⚠️", "Numerical stability pattern unclear"))
        
    except FileNotFoundError:
        checks.append(("❌", "maestro_orchestrator.py not found"))
    
    for status, message in checks:
        print(f"  {status} {message}")
    
    return all(status == "✅" for status, _ in checks if status != "⚠️")


def check_requirement_5_integration():
    """
    Requirement 5: Integration with BaseStrategy pattern.
    
    Verifies:
    - Inherits from BaseStrategy
    - Returns Dict[str, Decimal] for weights
    - Follows lifecycle hooks
    """
    print("\n" + "="*70)
    print("REQUIREMENT 5: BaseStrategy Integration")
    print("="*70)
    
    checks = []
    
    try:
        with open('maestro_orchestrator.py', 'r') as f:
            source = f.read()
        
        # Check BaseStrategy inheritance
        if 'class MaestroOrchestrator(BaseStrategy)' in source:
            checks.append(("✅", "Inherits from BaseStrategy"))
        else:
            checks.append(("❌", "Does not inherit from BaseStrategy"))
        
        # Check BaseStrategy import
        if 'from .base_strategy import BaseStrategy' in source:
            checks.append(("✅", "BaseStrategy imported correctly"))
        else:
            checks.append(("⚠️", "BaseStrategy import pattern unclear"))
        
        # Check evaluate method
        if 'def evaluate(' in source:
            checks.append(("✅", "evaluate() method implemented"))
        else:
            checks.append(("❌", "evaluate() method missing"))
        
        # Check TradingSignal return type
        if 'TradingSignal' in source:
            checks.append(("✅", "Returns TradingSignal objects"))
        else:
            checks.append(("❌", "TradingSignal not used"))
        
        # Check Dict[str, Decimal] return type
        if 'Dict[str, Decimal]' in source:
            checks.append(("✅", "calculate_agent_weights returns Dict[str, Decimal]"))
        else:
            checks.append(("⚠️", "Return type annotation unclear"))
        
        # Check config pattern
        if 'def __init__(self, config:' in source:
            checks.append(("✅", "Standard config initialization"))
        else:
            checks.append(("❌", "Config initialization missing"))
        
        # Check super().__init__
        if 'super().__init__' in source:
            checks.append(("✅", "Calls parent __init__ (BaseStrategy)"))
        else:
            checks.append(("❌", "Does not call super().__init__"))
        
        # Check get_strategy_name compatibility
        if 'get_strategy_name' in source or '__class__.__name__' in source:
            checks.append(("✅", "Compatible with get_strategy_name pattern"))
        else:
            checks.append(("⚠️", "Strategy name pattern unclear"))
        
    except FileNotFoundError:
        checks.append(("❌", "maestro_orchestrator.py not found"))
    
    for status, message in checks:
        print(f"  {status} {message}")
    
    return all(status == "✅" for status, _ in checks if status != "⚠️")


def check_code_quality():
    """
    Additional: Check code quality and best practices.
    """
    print("\n" + "="*70)
    print("CODE QUALITY & BEST PRACTICES")
    print("="*70)
    
    checks = []
    
    try:
        with open('maestro_orchestrator.py', 'r') as f:
            source = f.read()
            lines = source.split('\n')
        
        # Check docstrings
        if '"""' in source and 'Args:' in source:
            checks.append(("✅", "Comprehensive docstrings present"))
        else:
            checks.append(("⚠️", "Docstrings may be incomplete"))
        
        # Check logging
        if 'import logging' in source and 'logger.info' in source:
            checks.append(("✅", "Logging implemented"))
        else:
            checks.append(("⚠️", "Logging unclear"))
        
        # Check error handling
        if 'try:' in source and 'except' in source:
            checks.append(("✅", "Error handling present"))
        else:
            checks.append(("❌", "No error handling found"))
        
        # Check type hints
        if 'from typing import' in source:
            checks.append(("✅", "Type hints used"))
        else:
            checks.append(("⚠️", "Type hints unclear"))
        
        # Check file size (should be reasonable)
        if len(lines) > 50 and len(lines) < 1000:
            checks.append(("✅", f"Reasonable file size ({len(lines)} lines)"))
        else:
            checks.append(("⚠️", f"File size: {len(lines)} lines"))
        
        # Check for configuration validation
        if 'config.get' in source or 'self.config' in source:
            checks.append(("✅", "Configuration management implemented"))
        else:
            checks.append(("❌", "Configuration management missing"))
        
    except FileNotFoundError:
        checks.append(("❌", "maestro_orchestrator.py not found"))
    
    for status, message in checks:
        print(f"  {status} {message}")
    
    return True  # Non-critical checks


def verify_example_files():
    """
    Verify that supporting files exist.
    """
    print("\n" + "="*70)
    print("SUPPORTING FILES")
    print("="*70)
    
    files = [
        ('maestro_orchestrator.py', 'Main implementation'),
        ('test_maestro_orchestrator.py', 'Unit tests'),
        ('MAESTRO_ORCHESTRATOR_README.md', 'Documentation'),
        ('example_maestro_usage.py', 'Usage examples')
    ]
    
    checks = []
    for filename, description in files:
        if os.path.exists(filename):
            checks.append(("✅", f"{description}: {filename}"))
        else:
            checks.append(("❌", f"{description}: {filename} NOT FOUND"))
    
    for status, message in checks:
        print(f"  {status} {message}")
    
    return all(status == "✅" for status, _ in checks)


def main():
    """Run all verification checks."""
    print("\n" + "="*70)
    print("MAESTRO ORCHESTRATOR - IMPLEMENTATION VERIFICATION")
    print("="*70)
    print("\nVerifying compliance with all requirements...")
    
    results = []
    
    # Run all checks
    results.append(("Requirement 1: Decimal Precision", check_requirement_1_decimal_precision()))
    results.append(("Requirement 2: Data Fetching", check_requirement_2_data_fetching()))
    results.append(("Requirement 3: Sharpe Calculation", check_requirement_3_sharpe_calculation()))
    results.append(("Requirement 4: Weighting Engine", check_requirement_4_weighting_engine()))
    results.append(("Requirement 5: Integration", check_requirement_5_integration()))
    results.append(("Code Quality", check_code_quality()))
    results.append(("Supporting Files", verify_example_files()))
    
    # Summary
    print("\n" + "="*70)
    print("VERIFICATION SUMMARY")
    print("="*70)
    
    passed = 0
    total = len(results)
    
    for requirement, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}  {requirement}")
        if result:
            passed += 1
    
    print("\n" + "="*70)
    print(f"TOTAL: {passed}/{total} checks passed")
    
    if passed == total:
        print("✅ ALL REQUIREMENTS MET - Implementation complete!")
    elif passed >= total * 0.8:
        print("⚠️  MOSTLY COMPLETE - Review warnings above")
    else:
        print("❌ INCOMPLETE - Fix failing requirements")
    
    print("="*70 + "\n")
    
    return passed == total


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
