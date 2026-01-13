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

    # ---- Fill model controls (esp. important for OPTIONS backtests) ----
    # Slippage model:
    # - "bps": legacy behavior (price +/- slippage_bps)
    # - "worst_side_plus_spread": cross to worst-side (ask/bid) + spread penalty
    fill_model: str = "worst_side_plus_spread"

    # If bid/ask is missing, we synthesize a spread around `price` using these defaults.
    equity_default_spread_pct: Decimal = Decimal("0.0005")  # 5 bps
    equity_min_spread_abs: Decimal = Decimal("0.01")  # $0.01

    options_default_spread_pct: Decimal = Decimal("0.05")  # 5% of premium (conservative)
    options_min_spread_abs: Decimal = Decimal("0.05")  # $0.05 (typical options tick)

    # Additional adverse selection penalty in units of spread.
    # Example (BUY): fill = ask + (spread_penalty_mult * spread)
    spread_penalty_mult: Decimal = Decimal("0.25")
    

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
        
        # Lazy import: keep module importable in minimal CI/unit-test environments.
        from alpaca.data.historical import StockHistoricalDataClient  # type: ignore

        # Initialize Alpaca client for historical data
        self.data_client = StockHistoricalDataClient(api_key=alpaca_api_key, secret_key=alpaca_secret_key)
        
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
        
        # Lazy imports: allow importing this module without Alpaca SDK installed.
        from alpaca.data.requests import StockBarsRequest  # type: ignore
        from alpaca.data.timeframe import TimeFrame  # type: ignore

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

    def _synthesize_quote(self, *, price: Decimal, asset_class: str, metadata: Dict[str, Any]) -> Dict[str, Decimal]:
        """
        Build a bid/ask quote for fill modeling.

        Priority:
        1) explicit bid/ask in metadata (e.g., coming from recorded options quotes)
        2) synthesize around `price` using configured spread defaults
        """
        bid_raw = metadata.get("bid")
        ask_raw = metadata.get("ask")

        bid = Decimal(str(bid_raw)) if bid_raw is not None else Decimal("0")
        ask = Decimal(str(ask_raw)) if ask_raw is not None else Decimal("0")

        if bid > 0 and ask > 0 and ask >= bid:
            spread = ask - bid
            mid = (ask + bid) / Decimal("2")
            return {"bid": bid, "ask": ask, "mid": mid, "spread": spread}

        # Fall back to synthetic spread.
        if str(asset_class).upper() == "OPTIONS":
            spread_pct = self.config.options_default_spread_pct
            min_spread = self.config.options_min_spread_abs
        else:
            spread_pct = self.config.equity_default_spread_pct
            min_spread = self.config.equity_min_spread_abs

        mid = price if price > 0 else Decimal("0")
        spread = max(mid * spread_pct, min_spread) if mid > 0 else min_spread
        half = spread / Decimal("2")
        bid = max(Decimal("0"), mid - half)
        ask = max(Decimal("0"), mid + half)
        return {"bid": bid, "ask": ask, "mid": mid, "spread": spread}

    def _compute_fill_price(
        self,
        *,
        action: str,
        reference_price: Decimal,
        asset_class: str,
        metadata: Dict[str, Any],
    ) -> Tuple[Decimal, Decimal]:
        """
        Compute executed price and signed slippage vs reference.

        For fill_model="worst_side_plus_spread":
          BUY  fill = ask + spread_penalty_mult * spread
          SELL fill = bid - spread_penalty_mult * spread
        """
        action_u = str(action).upper().strip()
        model = str(self.config.fill_model or "bps").strip().lower()

        # Legacy bps model (no bid/ask needed).
        if model == "bps":
            slippage_pct = Decimal(str(self.config.slippage_bps)) / Decimal("10000")
            slippage_amt = reference_price * slippage_pct
            slippage = slippage_amt if action_u == "BUY" else -slippage_amt
            return (reference_price + slippage, slippage)

        # Spread-aware worst-side model (default).
        q = self._synthesize_quote(price=reference_price, asset_class=asset_class, metadata=metadata)
        bid, ask, spread = q["bid"], q["ask"], q["spread"]
        penalty = max(Decimal("0"), self.config.spread_penalty_mult) * max(Decimal("0"), spread)

        if action_u == "BUY":
            fill = ask + penalty
        elif action_u == "SELL":
            fill = max(Decimal("0"), bid - penalty)
        else:
            fill = reference_price

        slippage = fill - reference_price
        return (fill, slippage)
    
    def calculate_slippage(self, price: Decimal, action: str) -> Decimal:
        """
        Back-compat shim: returns signed slippage vs `price` using the configured fill model.

        Prefer `_compute_fill_price()` in new code (it returns both fill and slippage).
        """
        fill, slip = self._compute_fill_price(
            action=action,
            reference_price=price,
            asset_class="EQUITY",
            metadata={},
        )
        _ = fill
        return slip
    
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

            asset_class = str(metadata.get("asset_class") or "EQUITY").upper().strip()

            # Calculate quantity (account for fill model in advance)
            effective_price, _ = self._compute_fill_price(
                action="BUY",
                reference_price=price,
                asset_class=asset_class,
                metadata=metadata,
            )
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
        asset_class = str(metadata.get("asset_class") or "EQUITY").upper().strip()
        effective_price, slippage = self._compute_fill_price(
            action="BUY",
            reference_price=price,
            asset_class=asset_class,
            metadata=metadata,
        )
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
            price=effective_price,
            quantity=quantity,
            commission=commission,
            slippage=slippage,
            total_cost=total_cost,
            reasoning=reasoning,
            metadata=metadata
        )
        
        self.trades.append(trade)
        logger.info(
            f"BUY: {quantity} {symbol} @ ${effective_price} "
            f"(ref: ${price}, slippage: ${slippage:.4f}, total: ${total_cost:.2f})"
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
        asset_class = str(metadata.get("asset_class") or "EQUITY").upper().strip()
        effective_price, slippage = self._compute_fill_price(
            action="SELL",
            reference_price=price,
            asset_class=asset_class,
            metadata=metadata,
        )
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
            price=effective_price,
            quantity=quantity,
            commission=commission,
            slippage=slippage,
            total_cost=-total_proceeds,  # Negative because we receive cash
            reasoning=reasoning,
            metadata=metadata
        )
        
        self.trades.append(trade)
        logger.info(
            f"SELL: {quantity} {symbol} @ ${effective_price} "
            f"(ref: ${price}, slippage: ${slippage:.4f}, proceeds: ${total_proceeds:.2f})"
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
            # Note: we synthesize bid/ask so strategies can downgrade on spreads and
            # so fills can be modeled conservatively.
            q = self._synthesize_quote(
                price=price,
                asset_class="EQUITY",
                metadata={},
            )
            spread_pct = float(q["spread"] / q["mid"]) if q["mid"] > 0 else 0.0
            market_data = {
                "symbol": self.config.symbol,
                "price": float(price),
                "bid": float(q["bid"]),
                "ask": float(q["ask"]),
                "spread": float(q["spread"]),
                "spread_pct": spread_pct,
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
                            "asset_class": signal.asset_class.value,
                            "bid": market_data.get("bid"),
                            "ask": market_data.get("ask"),
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
                "slippage_bps": self.config.slippage_bps,
                "fill_model": self.config.fill_model,
                "spread_penalty_mult": float(self.config.spread_penalty_mult),
                "equity_default_spread_pct": float(self.config.equity_default_spread_pct),
                "equity_min_spread_abs": float(self.config.equity_min_spread_abs),
                "options_default_spread_pct": float(self.config.options_default_spread_pct),
                "options_min_spread_abs": float(self.config.options_min_spread_abs),
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
