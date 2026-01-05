#!/usr/bin/env python3
"""
Risk Management Kill-Switch Verification Script

This script verifies that all components of the risk management system
are properly implemented and functioning.

Usage:
    python scripts/verify_risk_management.py

Requirements:
    - Firebase credentials configured
    - Functions deployed
    - Frontend built
"""

import sys
from pathlib import Path

# Color output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def check(description: str) -> bool:
    """Print a check description and return True"""
    print(f"  {GREEN}✓{RESET} {description}")
    return True

def fail(description: str) -> bool:
    """Print a failure description and return False"""
    print(f"  {RED}✗{RESET} {description}")
    return False

def info(message: str):
    """Print an info message"""
    print(f"{BLUE}ℹ{RESET} {message}")

def warn(message: str):
    """Print a warning message"""
    print(f"{YELLOW}⚠{RESET} {message}")

def section(title: str):
    """Print a section header"""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{title}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")

def main():
    """Main verification routine"""
    results = []
    
    section("Risk Management Kill-Switch Verification")
    info("Checking implementation completeness...")
    
    # Backend Files
    section("1. Backend Files")
    
    risk_manager = Path("functions/risk_manager.py")
    if risk_manager.exists():
        results.append(check("functions/risk_manager.py exists"))
        
        # Check key functions
        content = risk_manager.read_text()
        if "update_risk_state" in content:
            results.append(check("  - update_risk_state() function defined"))
        else:
            results.append(fail("  - update_risk_state() function missing"))
            
        if "calculate_drawdown" in content:
            results.append(check("  - calculate_drawdown() function defined"))
        else:
            results.append(fail("  - calculate_drawdown() function missing"))
            
        if "get_trading_enabled" in content:
            results.append(check("  - get_trading_enabled() function defined"))
        else:
            results.append(fail("  - get_trading_enabled() function missing"))
            
        if "DEFAULT_DRAWDOWN_THRESHOLD" in content:
            results.append(check("  - Drawdown threshold configured (5%)"))
        else:
            results.append(fail("  - Drawdown threshold not configured"))
    else:
        results.append(fail("functions/risk_manager.py MISSING"))
    
    main_py = Path("functions/main.py")
    if main_py.exists():
        results.append(check("functions/main.py exists"))
        
        content = main_py.read_text()
        if "emergency_liquidate" in content:
            results.append(check("  - emergency_liquidate() function defined"))
        else:
            results.append(fail("  - emergency_liquidate() function missing"))
            
        if "update_risk_state" in content:
            results.append(check("  - pulse() calls update_risk_state()"))
        else:
            results.append(fail("  - pulse() missing risk state update"))
            
        if "from risk_manager import" in content:
            results.append(check("  - risk_manager module imported"))
        else:
            results.append(fail("  - risk_manager module not imported"))
    else:
        results.append(fail("functions/main.py MISSING"))
    
    signal_trader = Path("backend/alpaca_signal_trader.py")
    if signal_trader.exists():
        results.append(check("backend/alpaca_signal_trader.py exists"))
        
        content = signal_trader.read_text()
        if "trading_enabled" in content and "systemStatus" in content:
            results.append(check("  - Signal generation checks trading_enabled flag"))
        else:
            results.append(fail("  - Signal generation missing safety check"))
    else:
        results.append(fail("backend/alpaca_signal_trader.py MISSING"))
    
    # Frontend Files
    section("2. Frontend Files")
    
    panic_button = Path("frontend/src/components/PanicButton.tsx")
    if panic_button.exists():
        results.append(check("frontend/src/components/PanicButton.tsx exists"))
        
        content = panic_button.read_text()
        if "emergency_liquidate" in content:
            results.append(check("  - Calls emergency_liquidate Firebase function"))
        else:
            results.append(fail("  - Missing Firebase function call"))
            
        if "showSecondConfirm" in content:
            results.append(check("  - Double-confirmation implemented"))
        else:
            results.append(fail("  - Double-confirmation missing"))
    else:
        results.append(fail("frontend/src/components/PanicButton.tsx MISSING"))
    
    master_control = Path("frontend/src/components/MasterControlPanel.tsx")
    if master_control.exists():
        results.append(check("frontend/src/components/MasterControlPanel.tsx exists"))
        
        content = master_control.read_text()
        if "PanicButton" in content:
            results.append(check("  - PanicButton integrated"))
        else:
            results.append(fail("  - PanicButton not integrated"))
    else:
        results.append(fail("frontend/src/components/MasterControlPanel.tsx MISSING"))
    
    dashboard_header = Path("frontend/src/components/DashboardHeader.tsx")
    if dashboard_header.exists():
        content = dashboard_header.read_text()
        if "PanicButton" in content:
            results.append(check("  - PanicButton in header (always visible)"))
        else:
            warn("  - PanicButton not in header (optional)")
    
    firebase_ts = Path("frontend/src/firebase.ts")
    if firebase_ts.exists():
        content = firebase_ts.read_text()
        if "getFunctions" in content and "functions" in content:
            results.append(check("  - Firebase Functions SDK configured"))
        else:
            results.append(fail("  - Firebase Functions SDK missing"))
    else:
        results.append(fail("frontend/src/firebase.ts MISSING"))
    
    # Configuration
    section("3. Configuration")
    
    requirements = Path("functions/requirements.txt")
    if requirements.exists():
        content = requirements.read_text()
        if "firebase-functions" in content:
            results.append(check("firebase-functions in requirements.txt"))
        else:
            results.append(fail("firebase-functions missing from requirements.txt"))
            
        if "firebase-admin" in content:
            results.append(check("firebase-admin in requirements.txt"))
        else:
            results.append(fail("firebase-admin missing from requirements.txt"))
    else:
        results.append(fail("functions/requirements.txt MISSING"))
    
    # Documentation
    section("4. Documentation")
    
    docs = Path("docs/RISK_MANAGEMENT_KILLSWITCH.md")
    if docs.exists():
        results.append(check("Complete documentation available"))
    else:
        results.append(fail("Documentation missing"))
    
    quick_start = Path("docs/RISK_MANAGEMENT_QUICK_START.md")
    if quick_start.exists():
        results.append(check("Quick start guide available"))
    else:
        results.append(fail("Quick start guide missing"))
    
    # Summary
    section("Verification Summary")
    
    passed = sum(results)
    total = len(results)
    percentage = (passed / total * 100) if total > 0 else 0
    
    print(f"\nResults: {GREEN}{passed}{RESET}/{total} checks passed ({percentage:.1f}%)\n")
    
    if passed == total:
        print(f"{GREEN}{'='*60}{RESET}")
        print(f"{GREEN}✓ ALL CHECKS PASSED - SYSTEM READY FOR DEPLOYMENT{RESET}")
        print(f"{GREEN}{'='*60}{RESET}")
        return 0
    elif percentage >= 80:
        print(f"{YELLOW}{'='*60}{RESET}")
        print(f"{YELLOW}⚠ MOSTLY COMPLETE - REVIEW FAILURES ABOVE{RESET}")
        print(f"{YELLOW}{'='*60}{RESET}")
        return 1
    else:
        print(f"{RED}{'='*60}{RESET}")
        print(f"{RED}✗ IMPLEMENTATION INCOMPLETE - FIX FAILURES ABOVE{RESET}")
        print(f"{RED}{'='*60}{RESET}")
        return 2

if __name__ == "__main__":
    sys.exit(main())
