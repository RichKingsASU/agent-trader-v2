"""
Historical Backtester for Strategy Testing.

This module provides a simulation environment that uses BaseStrategy logic to test
trading strategies on historical data with realistic constraints.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import pytz

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from .base_strategy import BaseStrategy, SignalType

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Configuration for backtest execution."""
    symbol: str = "SPY"
    start_capital: Decimal = Decimal("100000.00")
    lookback_days: int = 30
    slippage_bps: int = 1  # 0.01% slippage per trade
    commission_per_trade: Decimal = Decimal("0.00")  # Commission if any
    position_size_pct: Decimal = Decimal("1.0")  # Max 100% allocation
    

@dataclass
class Trade:
    """Represents a single trade execution."""
    timestamp: datetime
    action: str  # BUY, SELL, CLOSE_ALL
    symbol: str
    price: Decimal
    quantity: int
    commission: Decimal
    slippage: Decimal
    total_cost: Decimal
    reasoning: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    """Represents a current position."""
    symbol: str
    quantity: int
    avg_entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    
    def update_price(self, new_price: Decimal) -> None:
        """Update current price and unrealized PnL."""
        self.current_price = new_price
        self.unrealized_pnl = (new_price - self.avg_entry_price) * Decimal(str(self.quantity))


@dataclass
class AccountState:
    """Represents account state at a point in time."""
    timestamp: datetime
    cash: Decimal
    equity: Decimal
    positions: Dict[str, Position] = field(default_factory=dict)
    
    def get_buying_power(self) -> Decimal:
        """Calculate available buying power (cash for now, can add margin later)."""
        return self.cash
    
    def to_snapshot(self) -> Dict[str, Any]:
        """Convert to account_snapshot format expected by strategies."""
        positions_list = []
        for symbol, pos in self.positions.items():
            positions_list.append({
                "symbol": symbol,
                "qty": str(pos.quantity),
                "avg_entry_price": str(pos.avg_entry_price),
                "current_price": str(pos.current_price),
                "unrealized_pl": str(pos.unrealized_pnl),
                "greeks": {}  # Filled in by backtester
            })
        
        return {
            "equity": str(self.equity),
            "buying_power": str(self.get_buying_power()),
            "cash": str(self.cash),
            "positions": positions_list
        }


class GreeksSimulator:
    """
    Simulates option Greeks for backtesting.
    
    In production, these would come from options market data.
    For backtesting, we simulate realistic Greeks based on price movements.
    """
    
    @staticmethod
    def simulate_greeks(
        underlying_price: float,
        strike: Optional[float] = None,
        time_to_expiry: float = 1.0,  # days
        implied_vol: float = 0.20  # 20% IV
    ) -> Dict[str, float]:
        """
        Simulate option Greeks using simplified Black-Scholes approximations.
        
        For 0DTE strategies, we'll simulate ATM options with realistic Greeks.
        
        Args:
            underlying_price: Current price of underlying
            strike: Strike price (defaults to ATM)
            time_to_expiry: Days to expiration
            implied_vol: Implied volatility (annualized)
        
        Returns:
            Dict with delta, gamma, theta, vega
        """
        if strike is None:
            strike = underlying_price  # ATM
        
        # Moneyness
        moneyness = underlying_price / strike
        
        # For ATM options near expiry (0DTE-like):
        # - Delta: ~0.5 for ATM, moves to 0 or 1 as ITM/OTM
        # - Gamma: Highest at ATM, especially near expiry
        # - Theta: Large negative (time decay)
        # - Vega: Moderate
        
        # Simplified delta calculation
        if moneyness > 1.05:  # ITM
            delta = 0.70 + (moneyness - 1.05) * 0.5
        elif moneyness < 0.95:  # OTM
            delta = 0.30 - (0.95 - moneyness) * 0.5
        else:  # ATM
            delta = 0.50
        
        delta = max(0.0, min(1.0, delta))
        
        # Gamma peaks at ATM and increases as expiry approaches
        atm_factor = 1.0 - abs(moneyness - 1.0) * 2
        atm_factor = max(0.0, atm_factor)
        gamma = 0.05 * atm_factor * (1.0 / max(time_to_expiry, 0.1))
        
        # Theta (time decay) increases near expiry
        theta = -0.02 * implied_vol * (1.0 / max(time_to_expiry, 0.1))
        
        # Vega (sensitivity to IV)
        vega = 0.1 * underlying_price * (time_to_expiry ** 0.5)
        
        return {
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta, 4),
            "vega": round(vega, 4)
        }


class Backtester:
    """
    Historical backtester that simulates strategy execution on historical data.
    
    Key Features:
    - No look-ahead bias: Only uses data available at each timestamp
    - Transaction costs: Applies slippage and commissions
    - Realistic execution: Simulates fills, position management
    - Greeks simulation: Generates realistic option Greeks
    """
    
    def __init__(
        self,
        strategy: BaseStrategy,
        config: BacktestConfig,
        alpaca_api_key: str,
        alpaca_secret_key: str
    ):
        """
        Initialize backtester.
        
        Args:
            strategy: The strategy instance to test
            config: Backtest configuration
            alpaca_api_key: Alpaca API key for historical data
            alpaca_secret_key: Alpaca API secret
        """
        self.strategy = strategy
        self.config = config
        
        # Initialize Alpaca client for historical data
        self.data_client = StockHistoricalDataClient(
            api_key=alpaca_api_key,
            secret_key=alpaca_secret_key
        )
        
        # State tracking
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, Decimal]] = []
        self.account_state: Optional[AccountState] = None
        
        # Greeks simulator
        self.greeks_sim = GreeksSimulator()
        
        logger.info(
            f"Backtester initialized: strategy={strategy.get_strategy_name()}, "
            f"symbol={config.symbol}, capital=${config.start_capital}"
        )
    
    def fetch_historical_data(self) -> List[Dict[str, Any]]:
        """
        Fetch 1-minute bars from Alpaca for the backtest period.
        
        Returns:
            List of bar dictionaries with timestamp, open, high, low, close, volume
        """
        end_date = datetime.now(pytz.UTC)
        start_date = end_date - timedelta(days=self.config.lookback_days)
        
        logger.info(
            f"Fetching historical data: {self.config.symbol} "
            f"from {start_date.date()} to {end_date.date()}"
        )
        
        request_params = StockBarsRequest(
            symbol_or_symbols=self.config.symbol,
            timeframe=TimeFrame.Minute,
            start=start_date,
            end=end_date
        )
        
        try:
            bars = self.data_client.get_stock_bars(request_params)
            
            # Convert to list of dicts
            bars_list = []
            for bar in bars[self.config.symbol]:
                bars_list.append({
                    "timestamp": bar.timestamp,
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": int(bar.volume)
                })
            
            logger.info(f"Fetched {len(bars_list)} bars for backtesting")
            return bars_list
            
        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            raise
    
    def calculate_slippage(self, price: Decimal, action: str) -> Decimal:
        """
        Calculate slippage based on action.
        
        Slippage simulates the difference between expected and actual execution price.
        - BUY: Pay slightly more (positive slippage)
        - SELL: Receive slightly less (negative slippage)
        
        Args:
            price: Intended execution price
            action: BUY or SELL
        
        Returns:
            Slippage amount in dollars
        """
        slippage_pct = Decimal(str(self.config.slippage_bps)) / Decimal("10000")
        slippage_amt = price * slippage_pct
        
        # BUY pays more, SELL receives less
        return slippage_amt if action == "BUY" else -slippage_amt
    
    def execute_trade(
        self,
        timestamp: datetime,
        action: str,
        price: Decimal,
        reasoning: str,
        metadata: Dict[str, Any]
    ) -> Optional[Trade]:
        """
        Execute a trade with realistic costs and position management.
        
        Args:
            timestamp: When the trade occurs
            action: BUY, SELL, or CLOSE_ALL
            price: Current market price
            reasoning: Strategy reasoning
            metadata: Additional trade metadata
        
        Returns:
            Trade object if executed, None if skipped
        """
        if action == "HOLD":
            return None
        
        # Handle CLOSE_ALL
        if action == "CLOSE_ALL":
            trades = []
            for symbol, position in list(self.account_state.positions.items()):
                if position.quantity > 0:
                    trade = self._execute_sell(
                        timestamp, symbol, price, position.quantity,
                        f"{reasoning} (Close All)", metadata
                    )
                    if trade:
                        trades.append(trade)
            return trades[0] if trades else None
        
        # Handle BUY
        if action == "BUY":
            # Calculate position size based on confidence and available capital
            confidence = metadata.get("confidence", 0.5)
            allocation_pct = Decimal(str(confidence)) * self.config.position_size_pct
            available_capital = self.account_state.get_buying_power()
            
            # Calculate quantity (account for slippage in advance)
            slippage = self.calculate_slippage(price, "BUY")
            effective_price = price + slippage
            max_quantity = int((available_capital * allocation_pct) / effective_price)
            
            if max_quantity <= 0:
                logger.warning(f"Insufficient capital for BUY: ${available_capital}")
                return None
            
            return self._execute_buy(
                timestamp, self.config.symbol, price, max_quantity,
                reasoning, metadata
            )
        
        # Handle SELL
        if action == "SELL":
            # Check if we have a position to sell
            position = self.account_state.positions.get(self.config.symbol)
            if not position or position.quantity <= 0:
                logger.warning(f"No position to sell for {self.config.symbol}")
                return None
            
            # Sell entire position
            return self._execute_sell(
                timestamp, self.config.symbol, price, position.quantity,
                reasoning, metadata
            )
        
        return None
    
    def _execute_buy(
        self,
        timestamp: datetime,
        symbol: str,
        price: Decimal,
        quantity: int,
        reasoning: str,
        metadata: Dict[str, Any]
    ) -> Trade:
        """Execute a BUY order."""
        slippage = self.calculate_slippage(price, "BUY")
        effective_price = price + slippage
        commission = self.config.commission_per_trade
        
        total_cost = effective_price * Decimal(str(quantity)) + commission
        
        # Update account state
        self.account_state.cash -= total_cost
        
        # Update or create position
        if symbol in self.account_state.positions:
            pos = self.account_state.positions[symbol]
            total_qty = pos.quantity + quantity
            total_cost_basis = (pos.avg_entry_price * Decimal(str(pos.quantity)) +
                              effective_price * Decimal(str(quantity)))
            pos.quantity = total_qty
            pos.avg_entry_price = total_cost_basis / Decimal(str(total_qty))
            pos.current_price = price
        else:
            self.account_state.positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                avg_entry_price=effective_price,
                current_price=price,
                unrealized_pnl=Decimal("0")
            )
        
        # Create trade record
        trade = Trade(
            timestamp=timestamp,
            action="BUY",
            symbol=symbol,
            price=price,
            quantity=quantity,
            commission=commission,
            slippage=slippage,
            total_cost=total_cost,
            reasoning=reasoning,
            metadata=metadata
        )
        
        self.trades.append(trade)
        logger.info(
            f"BUY: {quantity} {symbol} @ ${price} "
            f"(slippage: ${slippage:.4f}, total: ${total_cost:.2f})"
        )
        
        return trade
    
    def _execute_sell(
        self,
        timestamp: datetime,
        symbol: str,
        price: Decimal,
        quantity: int,
        reasoning: str,
        metadata: Dict[str, Any]
    ) -> Trade:
        """Execute a SELL order."""
        slippage = self.calculate_slippage(price, "SELL")
        effective_price = price + slippage  # slippage is negative for SELL
        commission = self.config.commission_per_trade
        
        total_proceeds = effective_price * Decimal(str(quantity)) - commission
        
        # Update account state
        self.account_state.cash += total_proceeds
        
        # Update position
        position = self.account_state.positions[symbol]
        position.quantity -= quantity
        
        # Remove position if fully closed
        if position.quantity <= 0:
            del self.account_state.positions[symbol]
        
        # Create trade record
        trade = Trade(
            timestamp=timestamp,
            action="SELL",
            symbol=symbol,
            price=price,
            quantity=quantity,
            commission=commission,
            slippage=slippage,
            total_cost=-total_proceeds,  # Negative because we receive cash
            reasoning=reasoning,
            metadata=metadata
        )
        
        self.trades.append(trade)
        logger.info(
            f"SELL: {quantity} {symbol} @ ${price} "
            f"(slippage: ${slippage:.4f}, proceeds: ${total_proceeds:.2f})"
        )
        
        return trade
    
    def update_equity(self, timestamp: datetime, current_price: Decimal) -> None:
        """
        Update account equity based on current market prices.
        
        Equity = Cash + Sum(position.quantity * current_price)
        """
        # Update position prices
        for position in self.account_state.positions.values():
            position.update_price(current_price)
        
        # Calculate total equity
        positions_value = sum(
            pos.current_price * Decimal(str(pos.quantity))
            for pos in self.account_state.positions.values()
        )
        
        self.account_state.equity = self.account_state.cash + positions_value
        self.account_state.timestamp = timestamp
        
        # Record in equity curve
        self.equity_curve.append((timestamp, self.account_state.equity))
    
    def run(self, regime: Optional[str] = None) -> Dict[str, Any]:
        """
        Run the backtest simulation.
        
        Args:
            regime: Optional market regime to pass to strategy (e.g., "LONG_GAMMA", "SHORT_GAMMA")
        
        Returns:
            Dictionary with backtest results including trades, equity curve, and metrics
        """
        logger.info("=" * 80)
        logger.info(f"Starting backtest: {self.strategy.get_strategy_name()}")
        logger.info("=" * 80)
        
        # Initialize account state
        self.account_state = AccountState(
            timestamp=datetime.now(pytz.UTC),
            cash=self.config.start_capital,
            equity=self.config.start_capital
        )
        
        # Fetch historical data
        bars = self.fetch_historical_data()
        
        if not bars:
            raise ValueError("No historical data available for backtesting")
        
        # Record initial equity
        self.equity_curve.append((bars[0]["timestamp"], self.config.start_capital))
        
        # Main simulation loop
        logger.info(f"Simulating {len(bars)} time steps...")
        
        for i, bar in enumerate(bars):
            timestamp = bar["timestamp"]
            price = Decimal(str(bar["close"]))
            
            # Update account equity with current market prices
            self.update_equity(timestamp, price)
            
            # Prepare market data for strategy (NO LOOK-AHEAD BIAS)
            # Only use data available at this timestamp
            market_data = {
                "symbol": self.config.symbol,
                "price": float(price),
                "timestamp": timestamp.isoformat(),
                "greeks": self.greeks_sim.simulate_greeks(
                    underlying_price=float(price),
                    time_to_expiry=1.0  # Simulate 0DTE-like options
                ),
                "volume": bar["volume"]
            }
            
            # Get account snapshot
            account_snapshot = self.account_state.to_snapshot()
            
            # Add simulated Greeks to positions
            for pos_data in account_snapshot["positions"]:
                pos_data["greeks"] = market_data["greeks"]
            
            # Evaluate strategy
            try:
                signal = self.strategy.evaluate(
                    market_data=market_data,
                    account_snapshot=account_snapshot,
                    regime=regime
                )
                
                # Execute trade based on signal
                if signal.signal_type != SignalType.HOLD:
                    self.execute_trade(
                        timestamp=timestamp,
                        action=signal.signal_type.value,
                        price=price,
                        reasoning=signal.reasoning,
                        metadata={
                            "confidence": signal.confidence,
                            **signal.metadata
                        }
                    )
            
            except Exception as e:
                logger.error(f"Error evaluating strategy at {timestamp}: {e}")
                continue
            
            # Progress logging
            if (i + 1) % 1000 == 0:
                logger.info(
                    f"Progress: {i + 1}/{len(bars)} bars "
                    f"({100 * (i + 1) / len(bars):.1f}%) - "
                    f"Equity: ${self.account_state.equity:,.2f}"
                )
        
        # Final equity update
        final_price = Decimal(str(bars[-1]["close"]))
        self.update_equity(bars[-1]["timestamp"], final_price)
        
        logger.info("=" * 80)
        logger.info(f"Backtest complete: {len(self.trades)} trades executed")
        logger.info(f"Final equity: ${self.account_state.equity:,.2f}")
        logger.info("=" * 80)
        
        # Compile results
        return {
            "config": {
                "symbol": self.config.symbol,
                "start_capital": float(self.config.start_capital),
                "lookback_days": self.config.lookback_days,
                "slippage_bps": self.config.slippage_bps
            },
            "strategy": self.strategy.get_strategy_name(),
            "trades": [self._trade_to_dict(t) for t in self.trades],
            "equity_curve": [
                {"timestamp": ts.isoformat(), "equity": float(eq)}
                for ts, eq in self.equity_curve
            ],
            "final_equity": float(self.account_state.equity),
            "total_trades": len(self.trades),
            "final_positions": [
                {
                    "symbol": pos.symbol,
                    "quantity": pos.quantity,
                    "avg_entry_price": float(pos.avg_entry_price),
                    "current_price": float(pos.current_price),
                    "unrealized_pnl": float(pos.unrealized_pnl)
                }
                for pos in self.account_state.positions.values()
            ]
        }
    
    @staticmethod
    def _trade_to_dict(trade: Trade) -> Dict[str, Any]:
        """Convert Trade object to dictionary."""
        return {
            "timestamp": trade.timestamp.isoformat(),
            "action": trade.action,
            "symbol": trade.symbol,
            "price": float(trade.price),
            "quantity": trade.quantity,
            "commission": float(trade.commission),
            "slippage": float(trade.slippage),
            "total_cost": float(trade.total_cost),
            "reasoning": trade.reasoning,
            "metadata": trade.metadata
        }
