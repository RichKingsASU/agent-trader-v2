import os
import sys
import logging
from datetime import date, timedelta

from alpaca.trading.client import TradingClient
from alpaca.trading.symbols import OptionSymbol
from alpaca.trading.enums import AssetClass
from alpaca.common.exceptions import APIError

logger = logging.getLogger(__name__)

def get_nearest_expiration(trading_client: TradingClient, underlying_symbol: str) -> date | None:
    """
    Finds the nearest upcoming expiration date for options of a given underlying symbol.

    Args:
        trading_client: An initialized Alpaca TradingClient instance.
        underlying_symbol: The symbol of the underlying asset (e.g., "SPY").

    Returns:
        The nearest expiration date as a date object, or None if not found or an error occurs.
    """
    logger.info(f"Fetching nearest expiration for {underlying_symbol}")
    try:
        # Get available expiration dates
        expirations = trading_client.get_option_expirations(underlying_symbol)

        if not expirations:
            logger.warning(f"No expiration dates found for underlying {underlying_symbol}")
            return None

        # Filter for future dates and find the minimum (nearest)
        today = date.today()
        future_expirations = [exp for exp in expirations if exp >= today]

        if not future_expirations:
            logger.warning(f"No future expiration dates found for underlying {underlying_symbol}")
            return None

        nearest_expiration = min(future_expirations)
        logger.info(f"Nearest expiration found: {nearest_expiration}")
        return nearest_expiration

    except APIError as e:
        logger.error(f"Alpaca API error fetching expirations for {underlying_symbol}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error finding nearest expiration for {underlying_symbol}: {e}")
        return None

def get_atm_strike(trading_client: TradingClient, underlying_symbol: str, expiration_date: date) -> float | None:
    """
    Finds the At-The-Money (ATM) strike price for a given option expiration.

    Args:
        trading_client: An initialized Alpaca TradingClient instance.
        underlying_symbol: The symbol of the underlying asset (e.g., "SPY").
        expiration_date: The expiration date for the options.

    Returns:
        The ATM strike price as a float, or None if not found or an error occurs.
    """
    logger.info(f"Fetching ATM strike for {underlying_symbol} expiring {expiration_date}")
    try:
        # Get the current price of the underlying asset
        underlying_asset = trading_client.get_asset(underlying_symbol)
        current_price = float(underlying_asset.last_price) # Assuming last_price is the most relevant for ATM

        # Fetch option chains for the specified expiration
        # We need to specify calls and puts to get strike prices
        # NOTE: Assumes alpaca-py supports fetching option chains with specific expirations directly
        # If not, we might need to fetch all and filter.
        # For now, let's assume a way to get strikes near current_price

        # A common approach is to fetch the chain and then filter.
        # Let's assume we can fetch calls for the given expiration.
        option_chain = trading_client.get_option_chain(
            underlying_symbol,
            expiration_date,
            asset_class=AssetClass.OPTION # Explicitly specify asset class
        )

        if not option_chain.call_options:
            logger.warning(f"No call options found for {underlying_symbol} expiring {expiration_date}")
            return None

        # Find the strike closest to the current price
        strikes = sorted([opt.strike_price for opt in option_chain.call_options])
        
        # Find strike closest to current_price
        closest_strike = min(strikes, key=lambda strike: abs(strike - current_price))
        
        logger.info(f"ATM strike found for {underlying_symbol} expiring {expiration_date}: {closest_strike} (underlying price: {current_price})")
        return closest_strike

    except APIError as e:
        logger.error(f"Alpaca API error fetching ATM strike for {underlying_symbol} expiring {expiration_date}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error finding ATM strike for {underlying_symbol} expiring {expiration_date}: {e}")
        return None

# Placeholder for validation if needed, can be expanded
def validate_option_contract(option_contract: dict) -> bool:
    """
    Basic validation for an option contract.
    Args:
        option_contract: A dictionary representing an option contract.
    Returns:
        True if valid, False otherwise.
    """
    if not option_contract:
        logger.warning("Option contract is empty or None.")
        return False
    # Add more specific validation checks here if necessary
    # e.g., check for required keys like 'symbol', 'strike_price', 'expiration_date', 'type'
    if not all(k in option_contract for k in ['symbol', 'strike_price', 'expiration_date', 'type']):
        logger.warning("Option contract is missing required keys.")
        return False
    return True

