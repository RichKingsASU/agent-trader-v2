from decimal import Decimal, getcontext
import math

# Institutional Precision
getcontext().prec = 28

def calculate_gex_logic(spot, strike, oi, gamma, call_put):
    """
    Standard GEX Calculation: 
    GEX = Gamma * Open Interest * Contract Size (100) * Spot Price^2 * 0.01
    """
    s = Decimal(str(spot))
    k = Decimal(str(strike))
    o = Decimal(str(oi))
    g = Decimal(str(gamma))
    
    # Directional adjustment (Puts are negative GEX)
    direction = Decimal('1') if call_put.upper() == 'CALL' else Decimal('-1')
    
    # Calculate GEX for a 1% move
    gex = g * o * Decimal('100') * (s**2) * Decimal('0.01') * direction
    return gex

def run_test():
    print("🧪 Executing Institutional GEX Engine Test...")
    
    # Test Scenario: NVDA $145.50
    test_result = calculate_gex_logic(145.50, 150.00, 5000, 0.0125, 'CALL')
    
    print(f"✅ Input: NVDA Call @ 150 Strike | Spot: $145.50")
    print(f"✅ Result: {test_result:,.2f} Notional GEX")
    
    if test_result > 0:
        print("📈 Status: Dealer is LONG GAMMA (Market Stability)")
    else:
        print("📉 Status: Dealer is SHORT GAMMA (Market Volatility)")

if __name__ == "__main__":
    run_test()
