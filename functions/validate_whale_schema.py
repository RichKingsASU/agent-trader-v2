from decimal import Decimal
from datetime import datetime, timedelta

def validate_flow_entry(entry):
    required_keys = ['ticker', 'premium', 'sentiment', 'vol_oi_ratio']
    for key in required_keys:
        if key not in entry:
            raise ValueError(f"Missing key: {key}")
    
    # Validation logic for Maestro readiness
    if not isinstance(entry['premium'], Decimal):
        print("⚠️ Warning: Premium should be Decimal for Maestro math.")
    
    # Conviction Logic Test
    is_high_conviction = (entry['premium'] > 100000 and 
                         entry['flowType'] == 'SWEEP' and 
                         entry['vol_oi_ratio'] > 1)
    
    return "🔥 High Conviction" if is_high_conviction else "✅ Standard Flow"

# Mock Data
mock_sweep = {
    'ticker': 'AAPL',
    'flowType': 'SWEEP',
    'sentiment': 'BULLISH',
    'premium': Decimal('250000.00'),
    'vol_oi_ratio': Decimal('1.5'),
    'timestamp': datetime.now()
}

print(f"Validation Result: {validate_flow_entry(mock_sweep)}")
