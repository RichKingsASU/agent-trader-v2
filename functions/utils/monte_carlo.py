"""
Monte Carlo Stress Testing Engine for Trading Strategies

This module implements a sophisticated Monte Carlo simulation engine that:
1. Generates 1,000+ market scenarios using Geometric Brownian Motion (GBM)
2. Injects "Black Swan" events in 10% of simulations
3. Simulates dynamic correlation convergence during crashes
4. Calculates comprehensive risk metrics (VaR, CVaR, Sharpe, Max Drawdown)
5. Tracks recovery time from drawdowns

Purpose: Stress-test trading strategies before live deployment to ensure they
can survive extreme market conditions.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Market regime classification."""
    NORMAL = "normal"
    CRASH = "crash"
    RECOVERY = "recovery"
    HIGH_VOLATILITY = "high_volatility"


@dataclass
class SimulationParameters:
    """Parameters for Monte Carlo simulation."""
    
    # Simulation configuration
    num_simulations: int = 1000
    num_days: int = 252  # Trading days in a year
    initial_capital: float = 100000.0
    
    # Market parameters (annualized)
    base_drift: float = 0.10  # 10% expected annual return
    base_volatility: float = 0.20  # 20% annual volatility
    risk_free_rate: float = 0.04  # 4% risk-free rate
    
    # Black Swan parameters
    black_swan_probability: float = 0.10  # 10% of simulations
    crash_magnitude_min: float = -0.10  # Minimum -10% crash
    crash_magnitude_max: float = -0.20  # Maximum -20% crash
    crash_day_min: int = 20  # Earliest crash day
    crash_day_max: int = 180  # Latest crash day
    
    # Correlation parameters
    normal_correlation: float = 0.50  # Normal inter-sector correlation
    crisis_correlation: float = 0.95  # Correlation during crisis (sectors move together)
    correlation_transition_days: int = 5  # Days to transition from normal to crisis correlation
    
    # Transaction costs
    slippage_bps: float = 5.0  # 5 basis points slippage per trade
    commission_per_trade: float = 1.0  # $1 per trade
    
    # Sector ETF configuration
    sectors: List[str] = field(default_factory=lambda: [
        "XLK",  # Technology
        "XLE",  # Energy
        "XLF",  # Financials
        "XLV",  # Healthcare
        "XLY",  # Consumer Discretionary
        "XLP",  # Consumer Staples
        "XLI",  # Industrials
        "XLB",  # Materials
        "XLU",  # Utilities
        "XLRE", # Real Estate
        "SPY",  # Broad Market
        "SHV",  # Cash/Safe Haven
    ])
    
    # Risk thresholds (for pass/fail criteria)
    max_var_95: float = 0.15  # Max 15% VaR at 95% confidence
    min_survival_rate: float = 0.99  # 99% of paths must survive
    max_drawdown: float = 0.25  # Max 25% drawdown
    min_sharpe: float = 1.0  # Minimum Sharpe ratio


@dataclass
class SimulationPath:
    """Represents a single simulation path."""
    
    path_id: str
    prices: Dict[str, np.ndarray]  # Symbol -> price array
    equity_curve: np.ndarray
    trades: List[Dict[str, Any]]
    
    # Path characteristics
    is_black_swan: bool = False
    crash_day: Optional[int] = None
    crash_magnitude: Optional[float] = None
    
    # Performance metrics
    final_equity: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    recovery_days: Optional[int] = None  # Days to recover from max drawdown
    num_trades: int = 0
    total_costs: float = 0.0


@dataclass
class RiskMetrics:
    """Comprehensive risk metrics from Monte Carlo simulation."""
    
    # Value at Risk
    var_95: float  # 95th percentile loss
    var_99: float  # 99th percentile loss
    
    # Conditional VaR (Expected Shortfall)
    cvar_95: float  # Average loss in worst 5%
    cvar_99: float  # Average loss in worst 1%
    
    # Survival and drawdown
    survival_rate: float  # % of paths that don't blow up
    mean_max_drawdown: float
    worst_drawdown: float
    
    # Returns and ratios
    mean_return: float
    median_return: float
    std_return: float
    mean_sharpe: float
    median_sharpe: float
    
    # Recovery metrics
    mean_recovery_days: Optional[float]
    median_recovery_days: Optional[float]
    paths_without_recovery: int  # Paths that never recovered
    
    # Distribution stats
    final_equity_distribution: Dict[str, float]  # percentiles
    
    # Pass/Fail assessment
    passes_stress_test: bool
    failure_reasons: List[str] = field(default_factory=list)


class MonteCarloSimulator:
    """
    Monte Carlo simulation engine for stress-testing trading strategies.
    
    This engine generates thousands of realistic market scenarios including:
    - Normal market conditions (GBM)
    - Black Swan crashes
    - Correlation convergence during stress
    - Dynamic strategy execution
    """
    
    def __init__(self, params: Optional[SimulationParameters] = None):
        """
        Initialize the Monte Carlo simulator.
        
        Args:
            params: Simulation parameters (uses defaults if None)
        """
        self.params = params or SimulationParameters()
        self.rng = np.random.default_rng(seed=None)  # Use random seed for production
        
    def _generate_gbm_path(
        self,
        initial_price: float,
        drift: float,
        volatility: float,
        num_days: int,
        dt: float = 1/252
    ) -> np.ndarray:
        """
        Generate a price path using Geometric Brownian Motion.
        
        dS/S = μ*dt + σ*dW
        
        Args:
            initial_price: Starting price
            drift: Expected return (annualized)
            volatility: Volatility (annualized)
            num_days: Number of trading days
            dt: Time step (1/252 for daily with 252 trading days/year)
            
        Returns:
            Array of prices for each day
        """
        # Generate random shocks
        shocks = self.rng.normal(0, 1, num_days)
        
        # Calculate returns using GBM formula
        returns = (drift - 0.5 * volatility**2) * dt + volatility * np.sqrt(dt) * shocks
        
        # Convert to price levels
        price_path = initial_price * np.exp(np.cumsum(returns))
        
        # Prepend initial price
        return np.concatenate([[initial_price], price_path])
    
    def _inject_black_swan(
        self,
        price_path: np.ndarray,
        crash_day: int,
        crash_magnitude: float,
        recovery_rate: float = 0.5
    ) -> np.ndarray:
        """
        Inject a Black Swan crash event into a price path.
        
        The crash occurs on crash_day with magnitude crash_magnitude,
        followed by gradual recovery over subsequent days.
        
        Args:
            price_path: Original price path
            crash_day: Day when crash occurs
            crash_magnitude: Size of crash (e.g., -0.15 for -15%)
            recovery_rate: How fast market recovers (0.5 = moderate recovery)
            
        Returns:
            Modified price path with crash injected
        """
        modified_path = price_path.copy()
        
        # Apply sudden crash
        crash_multiplier = 1 + crash_magnitude
        modified_path[crash_day:] *= crash_multiplier
        
        # Add gradual recovery over next 20-60 days
        recovery_days = int(abs(crash_magnitude) * 200)  # More severe crashes take longer to recover
        recovery_days = min(recovery_days, len(modified_path) - crash_day - 1)
        
        if recovery_days > 0:
            # Exponential recovery curve
            recovery_factor = np.exp(np.linspace(0, np.log(1.15), recovery_days))  # Recover 15% from crash bottom
            recovery_end = crash_day + recovery_days
            modified_path[crash_day:recovery_end] *= recovery_factor[:recovery_end - crash_day]
        
        return modified_path
    
    def _generate_correlated_shocks(
        self,
        num_assets: int,
        num_days: int,
        correlation: float
    ) -> np.ndarray:
        """
        Generate correlated random shocks for multiple assets.
        
        Uses Cholesky decomposition to induce correlation structure.
        
        Args:
            num_assets: Number of assets (sectors)
            num_days: Number of days
            correlation: Target correlation between assets
            
        Returns:
            Array of shape (num_assets, num_days) with correlated shocks
        """
        # Create correlation matrix
        corr_matrix = np.full((num_assets, num_assets), correlation)
        np.fill_diagonal(corr_matrix, 1.0)
        
        # Cholesky decomposition
        try:
            L = np.linalg.cholesky(corr_matrix)
        except np.linalg.LinAlgError:
            # If matrix is not positive definite, use identity (no correlation)
            logger.warning("Correlation matrix not positive definite, using uncorrelated shocks")
            L = np.eye(num_assets)
        
        # Generate independent shocks
        independent_shocks = self.rng.normal(0, 1, (num_assets, num_days))
        
        # Apply correlation structure
        correlated_shocks = L @ independent_shocks
        
        return correlated_shocks
    
    def _generate_multi_asset_paths(
        self,
        path_id: str,
        is_black_swan: bool = False
    ) -> Tuple[Dict[str, np.ndarray], Optional[int], Optional[float]]:
        """
        Generate price paths for all sector ETFs with proper correlation structure.
        
        Args:
            path_id: Unique identifier for this path
            is_black_swan: Whether to inject a Black Swan event
            
        Returns:
            Tuple of (price_dict, crash_day, crash_magnitude)
        """
        num_days = self.params.num_days
        sectors = self.params.sectors
        num_assets = len(sectors)
        
        # Determine crash parameters if this is a Black Swan path
        crash_day = None
        crash_magnitude = None
        
        if is_black_swan:
            crash_day = self.rng.integers(
                self.params.crash_day_min,
                self.params.crash_day_max
            )
            crash_magnitude = self.rng.uniform(
                self.params.crash_magnitude_min,
                self.params.crash_magnitude_max
            )
        
        # Generate correlation structure that transitions during crisis
        correlation_schedule = np.full(num_days, self.params.normal_correlation)
        
        if is_black_swan and crash_day is not None:
            # Transition to high correlation around crash
            transition_start = max(0, crash_day - self.params.correlation_transition_days)
            transition_end = min(num_days, crash_day + self.params.correlation_transition_days * 2)
            
            # Smooth transition using sigmoid
            for day in range(transition_start, transition_end):
                days_from_crash = day - crash_day
                # Sigmoid function for smooth transition
                t = days_from_crash / self.params.correlation_transition_days
                sigmoid = 1 / (1 + np.exp(-t))
                correlation_schedule[day] = (
                    self.params.normal_correlation * (1 - sigmoid) +
                    self.params.crisis_correlation * sigmoid
                )
        
        # Generate prices for each sector
        prices = {}
        
        # Use segment-wise generation with dynamic correlation
        segment_size = 10  # Generate in 10-day segments for dynamic correlation
        num_segments = math.ceil(num_days / segment_size)
        
        # Initial prices (normalized to 100)
        current_prices = {sector: 100.0 for sector in sectors}
        
        for segment_idx in range(num_segments):
            start_day = segment_idx * segment_size
            end_day = min(start_day + segment_size, num_days)
            segment_days = end_day - start_day
            
            # Average correlation for this segment
            segment_corr = np.mean(correlation_schedule[start_day:end_day])
            
            # Generate correlated shocks
            shocks = self._generate_correlated_shocks(num_assets, segment_days, segment_corr)
            
            # Generate prices for each sector
            for i, sector in enumerate(sectors):
                # Sector-specific parameters (some sectors are more volatile)
                sector_vol_multiplier = 1.0
                if sector == "XLE":  # Energy more volatile
                    sector_vol_multiplier = 1.3
                elif sector == "XLU":  # Utilities less volatile
                    sector_vol_multiplier = 0.7
                elif sector == "SHV":  # Cash is stable
                    sector_vol_multiplier = 0.05
                
                volatility = self.params.base_volatility * sector_vol_multiplier
                
                # Calculate returns
                dt = 1/252
                returns = (
                    (self.params.base_drift - 0.5 * volatility**2) * dt +
                    volatility * np.sqrt(dt) * shocks[i]
                )
                
                # Convert to prices
                segment_prices = current_prices[sector] * np.exp(np.cumsum(returns))
                
                # Store prices
                if sector not in prices:
                    prices[sector] = np.array([current_prices[sector]])
                
                prices[sector] = np.concatenate([prices[sector], segment_prices])
                
                # Update current price for next segment
                current_prices[sector] = segment_prices[-1]
        
        # Inject Black Swan event if applicable
        if is_black_swan and crash_day is not None:
            for sector in sectors:
                if sector != "SHV":  # Cash doesn't crash
                    # Different sectors crash by different amounts
                    sector_crash_mult = 1.0
                    if sector == "XLF":  # Financials crash hardest
                        sector_crash_mult = 1.3
                    elif sector == "XLU":  # Utilities crash less
                        sector_crash_mult = 0.7
                    
                    adjusted_crash = crash_magnitude * sector_crash_mult
                    prices[sector] = self._inject_black_swan(
                        prices[sector],
                        crash_day,
                        adjusted_crash,
                        recovery_rate=0.5
                    )
        
        return prices, crash_day, crash_magnitude
    
    def _calculate_transaction_cost(
        self,
        trade_value: float,
        slippage_bps: Optional[float] = None
    ) -> float:
        """
        Calculate transaction costs (slippage + commission).
        
        Args:
            trade_value: Dollar value of trade
            slippage_bps: Slippage in basis points (uses default if None)
            
        Returns:
            Total transaction cost
        """
        slippage_bps = slippage_bps or self.params.slippage_bps
        
        slippage_cost = abs(trade_value) * (slippage_bps / 10000)
        commission = self.params.commission_per_trade
        
        return slippage_cost + commission
    
    def simulate_strategy(
        self,
        strategy_evaluate_fn: Any,
        strategy_config: Optional[Dict[str, Any]] = None,
        save_all_paths: bool = False
    ) -> Tuple[List[SimulationPath], RiskMetrics]:
        """
        Run Monte Carlo simulation with a trading strategy.
        
        Args:
            strategy_evaluate_fn: Strategy evaluation function that takes
                (market_data, account_snapshot, regime) and returns TradingSignal
            strategy_config: Configuration for the strategy
            save_all_paths: Whether to save detailed data for all paths (memory intensive)
            
        Returns:
            Tuple of (simulation_paths, risk_metrics)
        """
        logger.info(f"Starting Monte Carlo simulation with {self.params.num_simulations} paths...")
        
        paths: List[SimulationPath] = []
        
        # Determine which paths will be Black Swans
        num_black_swans = int(self.params.num_simulations * self.params.black_swan_probability)
        black_swan_indices = set(
            self.rng.choice(self.params.num_simulations, num_black_swans, replace=False)
        )
        
        for sim_idx in range(self.params.num_simulations):
            is_black_swan = sim_idx in black_swan_indices
            path_id = f"sim_{uuid.uuid4().hex[:12]}"
            
            # Generate price paths for all assets
            prices, crash_day, crash_magnitude = self._generate_multi_asset_paths(
                path_id=path_id,
                is_black_swan=is_black_swan
            )
            
            # Simulate strategy execution
            equity_curve, trades = self._simulate_strategy_execution(
                prices=prices,
                strategy_evaluate_fn=strategy_evaluate_fn,
                strategy_config=strategy_config or {}
            )
            
            # Calculate path metrics
            path = SimulationPath(
                path_id=path_id,
                prices=prices if save_all_paths else {},  # Save memory
                equity_curve=equity_curve,
                trades=trades if save_all_paths else [],  # Save memory
                is_black_swan=is_black_swan,
                crash_day=crash_day,
                crash_magnitude=crash_magnitude,
            )
            
            # Calculate performance metrics for this path
            self._calculate_path_metrics(path)
            
            paths.append(path)
            
            # Log progress
            if (sim_idx + 1) % 100 == 0:
                logger.info(f"Completed {sim_idx + 1}/{self.params.num_simulations} simulations")
        
        # Calculate aggregate risk metrics
        risk_metrics = self._calculate_risk_metrics(paths)
        
        logger.info(f"Monte Carlo simulation complete. VaR(95%)={risk_metrics.var_95:.2%}, "
                   f"Sharpe={risk_metrics.mean_sharpe:.2f}, Pass={risk_metrics.passes_stress_test}")
        
        return paths, risk_metrics
    
    def _simulate_strategy_execution(
        self,
        prices: Dict[str, np.ndarray],
        strategy_evaluate_fn: Any,
        strategy_config: Dict[str, Any]
    ) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
        """
        Simulate day-by-day strategy execution.
        
        Args:
            prices: Price paths for all assets
            strategy_evaluate_fn: Strategy evaluation function
            strategy_config: Strategy configuration
            
        Returns:
            Tuple of (equity_curve, trades)
        """
        num_days = self.params.num_days
        equity = self.params.initial_capital
        equity_curve = [equity]
        trades = []
        
        # Current portfolio (symbol -> shares)
        portfolio: Dict[str, float] = {}
        cash = equity
        
        for day in range(1, num_days + 1):
            # Build market data snapshot
            market_data = {}
            for symbol, price_path in prices.items():
                if day < len(price_path):
                    market_data[symbol] = {
                        "symbol": symbol,
                        "price": float(price_path[day]),
                        "previous_price": float(price_path[day - 1]) if day > 0 else float(price_path[day]),
                    }
            
            # Build account snapshot
            portfolio_value = sum(
                portfolio.get(symbol, 0) * market_data.get(symbol, {}).get("price", 0)
                for symbol in portfolio.keys()
            )
            equity = cash + portfolio_value
            
            account_snapshot = {
                "equity": str(equity),
                "cash": str(cash),
                "buying_power": str(cash),
                "positions": [
                    {
                        "symbol": symbol,
                        "qty": qty,
                        "market_value": qty * market_data.get(symbol, {}).get("price", 0)
                    }
                    for symbol, qty in portfolio.items()
                    if qty != 0
                ]
            }
            
            # Determine market regime (simplified)
            regime = "NORMAL"
            # Check for crash conditions (all sectors down significantly)
            if len(market_data) > 2:
                avg_return = np.mean([
                    (data["price"] - data["previous_price"]) / data["previous_price"]
                    for data in market_data.values()
                    if data["symbol"] not in ["SHV", "SPY"]
                ])
                if avg_return < -0.05:  # 5% average decline
                    regime = "SHORT_GAMMA"  # Market stress
            
            # Call strategy
            try:
                signal = strategy_evaluate_fn(
                    market_data=market_data,
                    account_snapshot=account_snapshot,
                    regime=regime
                )
                
                # Execute signal if it's actionable
                if hasattr(signal, 'signal_type') and hasattr(signal, 'metadata'):
                    signal_type = signal.signal_type.value if hasattr(signal.signal_type, 'value') else str(signal.signal_type)
                    
                    # Handle rebalancing
                    if signal_type in ["BUY", "SELL"] and signal.metadata:
                        target_symbol = signal.metadata.get("symbol")
                        target_allocation = signal.metadata.get("allocation", 0.0)
                        
                        if target_symbol and target_symbol in market_data:
                            # Execute trade
                            target_value = equity * target_allocation
                            current_value = portfolio.get(target_symbol, 0) * market_data[target_symbol]["price"]
                            trade_value = target_value - current_value
                            
                            if abs(trade_value) > 10:  # Minimum $10 trade
                                # Calculate shares to trade
                                price = market_data[target_symbol]["price"]
                                shares_to_trade = trade_value / price
                                
                                # Apply transaction costs
                                cost = self._calculate_transaction_cost(abs(trade_value))
                                
                                # Update portfolio
                                portfolio[target_symbol] = portfolio.get(target_symbol, 0) + shares_to_trade
                                cash -= trade_value + cost
                                
                                # Record trade
                                trades.append({
                                    "day": day,
                                    "symbol": target_symbol,
                                    "shares": shares_to_trade,
                                    "price": price,
                                    "value": trade_value,
                                    "cost": cost,
                                    "signal_type": signal_type,
                                })
                    
                    # Handle CLOSE_ALL
                    elif signal_type == "CLOSE_ALL":
                        for symbol in list(portfolio.keys()):
                            if portfolio[symbol] != 0:
                                shares = portfolio[symbol]
                                price = market_data.get(symbol, {}).get("price", 0)
                                value = shares * price
                                cost = self._calculate_transaction_cost(abs(value))
                                
                                cash += value - cost
                                
                                trades.append({
                                    "day": day,
                                    "symbol": symbol,
                                    "shares": -shares,
                                    "price": price,
                                    "value": value,
                                    "cost": cost,
                                    "signal_type": "CLOSE",
                                })
                                
                                portfolio[symbol] = 0
            
            except Exception as e:
                logger.warning(f"Strategy evaluation failed on day {day}: {e}")
            
            # Update equity curve
            portfolio_value = sum(
                portfolio.get(symbol, 0) * market_data.get(symbol, {}).get("price", 0)
                for symbol in portfolio.keys()
            )
            equity = cash + portfolio_value
            equity_curve.append(equity)
        
        return np.array(equity_curve), trades
    
    def _calculate_path_metrics(self, path: SimulationPath) -> None:
        """
        Calculate performance metrics for a single path.
        
        Modifies path object in-place.
        """
        equity_curve = path.equity_curve
        initial_equity = self.params.initial_capital
        
        # Final equity and return
        path.final_equity = float(equity_curve[-1])
        path.total_return = (path.final_equity - initial_equity) / initial_equity
        
        # Max drawdown
        peak = equity_curve[0]
        max_dd = 0.0
        drawdown_start = None
        recovery_day = None
        
        for i, equity in enumerate(equity_curve):
            if equity > peak:
                peak = equity
                if drawdown_start is not None and recovery_day is None:
                    recovery_day = i
            
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
                drawdown_start = i
        
        path.max_drawdown = max_dd
        
        # Recovery time
        if drawdown_start is not None and recovery_day is not None:
            path.recovery_days = recovery_day - drawdown_start
        
        # Sharpe ratio
        if len(equity_curve) > 1:
            returns = np.diff(equity_curve) / equity_curve[:-1]
            if len(returns) > 0:
                mean_return = np.mean(returns)
                std_return = np.std(returns)
                
                if std_return > 0:
                    # Annualize
                    annual_return = mean_return * 252
                    annual_std = std_return * np.sqrt(252)
                    path.sharpe_ratio = (annual_return - self.params.risk_free_rate) / annual_std
                else:
                    path.sharpe_ratio = 0.0
        
        # Trade statistics
        path.num_trades = len(path.trades)
        path.total_costs = sum(trade.get("cost", 0) for trade in path.trades)
    
    def _calculate_risk_metrics(self, paths: List[SimulationPath]) -> RiskMetrics:
        """
        Calculate aggregate risk metrics from all simulation paths.
        
        Args:
            paths: List of all simulation paths
            
        Returns:
            Comprehensive risk metrics
        """
        # Extract metrics
        returns = np.array([p.total_return for p in paths])
        max_drawdowns = np.array([p.max_drawdown for p in paths])
        sharpe_ratios = np.array([p.sharpe_ratio for p in paths])
        final_equities = np.array([p.final_equity for p in paths])
        
        recovery_days = [p.recovery_days for p in paths if p.recovery_days is not None]
        
        # Value at Risk (VaR)
        var_95 = -np.percentile(returns, 5)  # Worst 5%
        var_99 = -np.percentile(returns, 1)  # Worst 1%
        
        # Conditional VaR (CVaR / Expected Shortfall)
        worst_5_pct = returns[returns <= np.percentile(returns, 5)]
        worst_1_pct = returns[returns <= np.percentile(returns, 1)]
        
        cvar_95 = -np.mean(worst_5_pct) if len(worst_5_pct) > 0 else 0.0
        cvar_99 = -np.mean(worst_1_pct) if len(worst_1_pct) > 0 else 0.0
        
        # Survival rate (paths that don't go to zero)
        survival_rate = np.sum(final_equities > 0) / len(paths)
        
        # Return statistics
        mean_return = float(np.mean(returns))
        median_return = float(np.median(returns))
        std_return = float(np.std(returns))
        
        # Sharpe statistics
        mean_sharpe = float(np.mean(sharpe_ratios))
        median_sharpe = float(np.median(sharpe_ratios))
        
        # Drawdown statistics
        mean_max_drawdown = float(np.mean(max_drawdowns))
        worst_drawdown = float(np.max(max_drawdowns))
        
        # Recovery statistics
        mean_recovery = float(np.mean(recovery_days)) if recovery_days else None
        median_recovery = float(np.median(recovery_days)) if recovery_days else None
        paths_without_recovery = len([p for p in paths if p.recovery_days is None])
        
        # Distribution percentiles
        final_equity_distribution = {
            "p1": float(np.percentile(final_equities, 1)),
            "p5": float(np.percentile(final_equities, 5)),
            "p25": float(np.percentile(final_equities, 25)),
            "p50": float(np.percentile(final_equities, 50)),
            "p75": float(np.percentile(final_equities, 75)),
            "p95": float(np.percentile(final_equities, 95)),
            "p99": float(np.percentile(final_equities, 99)),
        }
        
        # Pass/Fail assessment
        failure_reasons = []
        
        if var_95 > self.params.max_var_95:
            failure_reasons.append(
                f"VaR(95%)={var_95:.2%} exceeds limit of {self.params.max_var_95:.2%}"
            )
        
        if survival_rate < self.params.min_survival_rate:
            failure_reasons.append(
                f"Survival rate={survival_rate:.2%} below minimum of {self.params.min_survival_rate:.2%}"
            )
        
        if worst_drawdown > self.params.max_drawdown:
            failure_reasons.append(
                f"Max drawdown={worst_drawdown:.2%} exceeds limit of {self.params.max_drawdown:.2%}"
            )
        
        if mean_sharpe < self.params.min_sharpe:
            failure_reasons.append(
                f"Mean Sharpe={mean_sharpe:.2f} below minimum of {self.params.min_sharpe:.2f}"
            )
        
        passes_stress_test = len(failure_reasons) == 0
        
        return RiskMetrics(
            var_95=var_95,
            var_99=var_99,
            cvar_95=cvar_95,
            cvar_99=cvar_99,
            survival_rate=survival_rate,
            mean_max_drawdown=mean_max_drawdown,
            worst_drawdown=worst_drawdown,
            mean_return=mean_return,
            median_return=median_return,
            std_return=std_return,
            mean_sharpe=mean_sharpe,
            median_sharpe=median_sharpe,
            mean_recovery_days=mean_recovery,
            median_recovery_days=median_recovery,
            paths_without_recovery=paths_without_recovery,
            final_equity_distribution=final_equity_distribution,
            passes_stress_test=passes_stress_test,
            failure_reasons=failure_reasons,
        )
    
    def export_results(
        self,
        paths: List[SimulationPath],
        risk_metrics: RiskMetrics
    ) -> Dict[str, Any]:
        """
        Export simulation results to a JSON-serializable format.
        
        Args:
            paths: List of simulation paths
            risk_metrics: Risk metrics
            
        Returns:
            Dictionary with all results
        """
        return {
            "metadata": {
                "num_simulations": len(paths),
                "num_days": self.params.num_days,
                "initial_capital": self.params.initial_capital,
                "simulation_timestamp": datetime.utcnow().isoformat(),
            },
            "parameters": asdict(self.params),
            "risk_metrics": asdict(risk_metrics),
            "paths_summary": [
                {
                    "path_id": p.path_id,
                    "is_black_swan": p.is_black_swan,
                    "crash_day": p.crash_day,
                    "crash_magnitude": p.crash_magnitude,
                    "final_equity": p.final_equity,
                    "total_return": p.total_return,
                    "max_drawdown": p.max_drawdown,
                    "sharpe_ratio": p.sharpe_ratio,
                    "recovery_days": p.recovery_days,
                    "num_trades": p.num_trades,
                    "total_costs": p.total_costs,
                    "equity_curve_sample": [
                        float(p.equity_curve[i])
                        for i in [0, len(p.equity_curve)//4, len(p.equity_curve)//2,
                                 3*len(p.equity_curve)//4, -1]
                    ] if len(p.equity_curve) > 0 else [],
                }
                for p in paths
            ],
        }
