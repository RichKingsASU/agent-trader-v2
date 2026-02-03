
import sys

try:
    import alpaca_trade_api
    print('alpaca-trade-api is installed')
except ImportError:
    print('alpaca-trade-api not installed')

try:
    import alpaca_py
    print('alpaca-py is installed')
except ImportError:
    print('alpaca-py not installed')
