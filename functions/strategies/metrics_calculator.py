"""
Performance Metrics Calculator for Backtesting.

Calculates key performance metrics for evaluating trading strategies:
- Sharpe Ratio: Risk-adjusted return
- Maximum Drawdown: Peak-to-trough loss
- Win Rate: Percentage of profitable trades
- Other metrics: Total return, volatility, etc.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Tuple
import math

logger = logging.getLogger(__name__)


class MetricsCalculator:
    """
    Calculate comprehensive performance metrics for backtested strategies.
    
    Metrics include:
    - Returns: Total return, annualized return
    - Risk: Volatility, maximum drawdown, Sharpe ratio
    - Trade Analysis: Win rate, average win/loss, profit factor
    """
    
    def __init__(self):
        """Initialize the metrics calculator."""
        self.TRADING_DAYS_PER_YEAR = 252
        self.RISK_FREE_RATE = 0.04  # 4% annualized risk-free rate
    
    def calculate_all_metrics(
        self,
        equity_curve: List[Tuple[datetime, Decimal]],
        trades: List[Dict[str, Any]],
        start_capital: Decimal
    ) -> Dict[str, Any]:
        """
        Calculate all performance metrics.
        
        Args:
            equity_curve: List of (timestamp, equity) tuples
            trades: List of trade dictionaries
            start_capital: Initial capital
        
        Returns:
            Dictionary with all calculated metrics
        """
        if not equity_curve or len(equity_curve) < 2:
            return self._empty_metrics()
        
        # Calculate return metrics
        final_equity = equity_curve[-1][1]
        total_return = self.calculate_total_return(start_capital, final_equity)
        annualized_return = self.calculate_annualized_return(
            equity_curve, start_capital
        )
        
        # Calculate risk metrics
        sharpe_ratio = self.calculate_sharpe_ratio(equity_curve, start_capital)
        max_drawdown, max_dd_pct = self.calculate_max_drawdown(equity_curve)
        volatility = self.calculate_volatility(equity_curve)
        
        # Calculate trade metrics
        trade_metrics = self.calculate_trade_metrics(trades, start_capital)
        
        # Calculate calmar ratio (return / max drawdown)
        calmar_ratio = (
            annualized_return / abs(max_dd_pct)
            if max_dd_pct != 0 else 0
        )
        
        # Calculate sortino ratio (downside risk-adjusted return)
        sortino_ratio = self.calculate_sortino_ratio(equity_curve, start_capital)
        
        return {
            # Return Metrics
            "total_return_pct": round(total_return * 100, 2),
            "annualized_return_pct": round(annualized_return * 100, 2),
            "final_equity": float(final_equity),
            "start_capital": float(start_capital),
            "net_profit": float(final_equity - start_capital),
            
            # Risk Metrics
            "sharpe_ratio": round(sharpe_ratio, 3),
            "sortino_ratio": round(sortino_ratio, 3),
            "calmar_ratio": round(calmar_ratio, 3),
            "max_drawdown_dollars": round(float(max_drawdown), 2),
            "max_drawdown_pct": round(max_dd_pct * 100, 2),
            "volatility_annualized_pct": round(volatility * 100, 2),
            
            # Trade Metrics
            **trade_metrics,
            
            # Period
            "start_date": equity_curve[0][0].isoformat(),
            "end_date": equity_curve[-1][0].isoformat(),
            "trading_days": len(equity_curve)
        }
    
    def calculate_total_return(
        self,
        start_capital: Decimal,
        final_equity: Decimal
    ) -> float:
        """
        Calculate total return.
        
        Total Return = (Final Equity - Start Capital) / Start Capital
        
        Returns:
            Total return as decimal (e.g., 0.15 = 15%)
        """
        if start_capital <= 0:
            return 0.0
        
        return float((final_equity - start_capital) / start_capital)
    
    def calculate_annualized_return(
        self,
        equity_curve: List[Tuple[datetime, Decimal]],
        start_capital: Decimal
    ) -> float:
        """
        Calculate annualized return.
        
        Annualized Return = (Final / Start) ^ (252 / Trading Days) - 1
        
        Returns:
            Annualized return as decimal
        """
        if not equity_curve or len(equity_curve) < 2:
            return 0.0
        
        final_equity = equity_curve[-1][1]
        trading_days = len(equity_curve)
        
        if start_capital <= 0 or trading_days == 0:
            return 0.0
        
        # Calculate compounded annual growth rate
        total_return = float(final_equity / start_capital)
        years = trading_days / self.TRADING_DAYS_PER_YEAR
        
        if total_return <= 0 or years <= 0:
            return 0.0
        
        annualized = (total_return ** (1 / years)) - 1
        return annualized
    
    def calculate_sharpe_ratio(
        self,
        equity_curve: List[Tuple[datetime, Decimal]],
        start_capital: Decimal
    ) -> float:
        """
        Calculate Sharpe Ratio (risk-adjusted return).
        
        Sharpe Ratio = (Mean Return - Risk Free Rate) / Std Dev of Returns
        
        A higher Sharpe ratio indicates better risk-adjusted performance:
        - < 1.0: Poor
        - 1.0 - 2.0: Good
        - > 2.0: Excellent
        
        Returns:
            Sharpe ratio (annualized)
        """
        if not equity_curve or len(equity_curve) < 2:
            return 0.0
        
        # Calculate period returns
        returns = self._calculate_period_returns(equity_curve)
        
        if not returns:
            return 0.0
        
        # Calculate mean return
        mean_return = sum(returns) / len(returns)
        
        # Calculate standard deviation of returns
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance)
        
        if std_dev == 0:
            return 0.0
        
        # Calculate daily risk-free rate
        daily_rf_rate = self.RISK_FREE_RATE / self.TRADING_DAYS_PER_YEAR
        
        # Calculate Sharpe ratio
        sharpe = (mean_return - daily_rf_rate) / std_dev
        
        # Annualize
        sharpe_annualized = sharpe * math.sqrt(self.TRADING_DAYS_PER_YEAR)
        
        return sharpe_annualized
    
    def calculate_sortino_ratio(
        self,
        equity_curve: List[Tuple[datetime, Decimal]],
        start_capital: Decimal
    ) -> float:
        """
        Calculate Sortino Ratio (downside risk-adjusted return).
        
        Similar to Sharpe but only considers downside volatility.
        
        Returns:
            Sortino ratio (annualized)
        """
        if not equity_curve or len(equity_curve) < 2:
            return 0.0
        
        # Calculate period returns
        returns = self._calculate_period_returns(equity_curve)
        
        if not returns:
            return 0.0
        
        # Calculate mean return
        mean_return = sum(returns) / len(returns)
        
        # Calculate downside deviation (only negative returns)
        daily_rf_rate = self.RISK_FREE_RATE / self.TRADING_DAYS_PER_YEAR
        downside_returns = [min(0, r - daily_rf_rate) for r in returns]
        downside_variance = sum(r ** 2 for r in downside_returns) / len(returns)
        downside_std = math.sqrt(downside_variance)
        
        if downside_std == 0:
            return 0.0
        
        # Calculate Sortino ratio
        sortino = (mean_return - daily_rf_rate) / downside_std
        
        # Annualize
        sortino_annualized = sortino * math.sqrt(self.TRADING_DAYS_PER_YEAR)
        
        return sortino_annualized
    
    def calculate_max_drawdown(
        self,
        equity_curve: List[Tuple[datetime, Decimal]]
    ) -> Tuple[Decimal, float]:
        """
        Calculate Maximum Drawdown (peak-to-trough loss).
        
        Max Drawdown is the largest percentage drop from a peak to a trough.
        It measures the worst-case loss an investor would have experienced.
        
        Returns:
            Tuple of (max_drawdown_dollars, max_drawdown_percentage)
        """
        if not equity_curve or len(equity_curve) < 2:
            return Decimal("0"), 0.0
        
        max_drawdown = Decimal("0")
        max_drawdown_pct = 0.0
        peak_equity = equity_curve[0][1]
        
        for timestamp, equity in equity_curve:
            # Update peak if we've reached a new high
            if equity > peak_equity:
                peak_equity = equity
            
            # Calculate drawdown from peak
            drawdown = peak_equity - equity
            drawdown_pct = float(drawdown / peak_equity) if peak_equity > 0 else 0.0
            
            # Update max drawdown
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_pct = drawdown_pct
        
        return max_drawdown, max_drawdown_pct
    
    def calculate_volatility(
        self,
        equity_curve: List[Tuple[datetime, Decimal]]
    ) -> float:
        """
        Calculate annualized volatility of returns.
        
        Volatility = Standard Deviation of Returns * sqrt(252)
        
        Returns:
            Annualized volatility as decimal (e.g., 0.15 = 15%)
        """
        if not equity_curve or len(equity_curve) < 2:
            return 0.0
        
        # Calculate period returns
        returns = self._calculate_period_returns(equity_curve)
        
        if not returns:
            return 0.0
        
        # Calculate standard deviation
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance)
        
        # Annualize
        annualized_vol = std_dev * math.sqrt(self.TRADING_DAYS_PER_YEAR)
        
        return annualized_vol
    
    def calculate_trade_metrics(
        self,
        trades: List[Dict[str, Any]],
        start_capital: Decimal
    ) -> Dict[str, Any]:
        """
        Calculate trade-level performance metrics.
        
        Args:
            trades: List of trade dictionaries
            start_capital: Initial capital
        
        Returns:
            Dictionary with trade metrics
        """
        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate_pct": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "largest_win": 0.0,
                "largest_loss": 0.0,
                "profit_factor": 0.0,
                "avg_trade_pnl": 0.0
            }
        
        # Separate trades into pairs (buy/sell)
        buy_trades = {}
        completed_trades = []
        
        for trade in trades:
            symbol = trade["symbol"]
            action = trade["action"]
            
            if action == "BUY":
                if symbol not in buy_trades:
                    buy_trades[symbol] = []
                buy_trades[symbol].append(trade)
            
            elif action == "SELL":
                if symbol in buy_trades and buy_trades[symbol]:
                    # Match with most recent buy
                    buy_trade = buy_trades[symbol].pop(0)
                    
                    # Calculate P&L for this round trip
                    buy_cost = abs(buy_trade["total_cost"])
                    sell_proceeds = abs(trade["total_cost"])
                    pnl = sell_proceeds - buy_cost
                    
                    completed_trades.append({
                        "pnl": pnl,
                        "buy": buy_trade,
                        "sell": trade
                    })
        
        if not completed_trades:
            return {
                "total_trades": len(trades),
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate_pct": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "largest_win": 0.0,
                "largest_loss": 0.0,
                "profit_factor": 0.0,
                "avg_trade_pnl": 0.0
            }
        
        # Calculate metrics
        winning_trades = [t for t in completed_trades if t["pnl"] > 0]
        losing_trades = [t for t in completed_trades if t["pnl"] < 0]
        
        total_wins = sum(t["pnl"] for t in winning_trades)
        total_losses = abs(sum(t["pnl"] for t in losing_trades))
        
        win_rate = len(winning_trades) / len(completed_trades) if completed_trades else 0
        avg_win = total_wins / len(winning_trades) if winning_trades else 0
        avg_loss = total_losses / len(losing_trades) if losing_trades else 0
        
        largest_win = max((t["pnl"] for t in winning_trades), default=0)
        largest_loss = min((t["pnl"] for t in losing_trades), default=0)
        
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        avg_trade_pnl = sum(t["pnl"] for t in completed_trades) / len(completed_trades)
        
        return {
            "total_trades": len(completed_trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate_pct": round(win_rate * 100, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "largest_win": round(largest_win, 2),
            "largest_loss": round(largest_loss, 2),
            "profit_factor": round(profit_factor, 3),
            "avg_trade_pnl": round(avg_trade_pnl, 2)
        }
    
    def _calculate_period_returns(
        self,
        equity_curve: List[Tuple[datetime, Decimal]]
    ) -> List[float]:
        """
        Calculate period-over-period returns.
        
        Returns:
            List of decimal returns for each period
        """
        if len(equity_curve) < 2:
            return []
        
        returns = []
        for i in range(1, len(equity_curve)):
            prev_equity = equity_curve[i - 1][1]
            curr_equity = equity_curve[i][1]
            
            if prev_equity > 0:
                period_return = float((curr_equity - prev_equity) / prev_equity)
                returns.append(period_return)
        
        return returns
    
    def _empty_metrics(self) -> Dict[str, Any]:
        """Return empty metrics structure."""
        return {
            "total_return_pct": 0.0,
            "annualized_return_pct": 0.0,
            "final_equity": 0.0,
            "start_capital": 0.0,
            "net_profit": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "calmar_ratio": 0.0,
            "max_drawdown_dollars": 0.0,
            "max_drawdown_pct": 0.0,
            "volatility_annualized_pct": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate_pct": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
            "profit_factor": 0.0,
            "avg_trade_pnl": 0.0,
            "start_date": "",
            "end_date": "",
            "trading_days": 0
        }
    
    def format_metrics_report(self, metrics: Dict[str, Any]) -> str:
        """
        Format metrics into a human-readable report.
        
        Args:
            metrics: Dictionary of calculated metrics
        
        Returns:
            Formatted string report
        """
        report = []
        report.append("=" * 80)
        report.append("BACKTEST PERFORMANCE REPORT")
        report.append("=" * 80)
        report.append("")
        
        report.append("RETURN METRICS:")
        report.append(f"  Total Return:          {metrics['total_return_pct']:>10.2f}%")
        report.append(f"  Annualized Return:     {metrics['annualized_return_pct']:>10.2f}%")
        report.append(f"  Net Profit:            ${metrics['net_profit']:>10,.2f}")
        report.append("")
        
        report.append("RISK METRICS:")
        report.append(f"  Sharpe Ratio:          {metrics['sharpe_ratio']:>10.3f}")
        report.append(f"  Sortino Ratio:         {metrics['sortino_ratio']:>10.3f}")
        report.append(f"  Calmar Ratio:          {metrics['calmar_ratio']:>10.3f}")
        report.append(f"  Max Drawdown:          {metrics['max_drawdown_pct']:>10.2f}% (${metrics['max_drawdown_dollars']:,.2f})")
        report.append(f"  Volatility:            {metrics['volatility_annualized_pct']:>10.2f}%")
        report.append("")
        
        report.append("TRADE METRICS:")
        report.append(f"  Total Trades:          {metrics['total_trades']:>10}")
        report.append(f"  Winning Trades:        {metrics['winning_trades']:>10}")
        report.append(f"  Losing Trades:         {metrics['losing_trades']:>10}")
        report.append(f"  Win Rate:              {metrics['win_rate_pct']:>10.2f}%")
        report.append(f"  Avg Win:               ${metrics['avg_win']:>10,.2f}")
        report.append(f"  Avg Loss:              ${metrics['avg_loss']:>10,.2f}")
        report.append(f"  Largest Win:           ${metrics['largest_win']:>10,.2f}")
        report.append(f"  Largest Loss:          ${metrics['largest_loss']:>10,.2f}")
        report.append(f"  Profit Factor:         {metrics['profit_factor']:>10.3f}")
        report.append("")
        
        report.append("PERIOD:")
        report.append(f"  Start Date:            {metrics['start_date'][:10]}")
        report.append(f"  End Date:              {metrics['end_date'][:10]}")
        report.append(f"  Trading Days:          {metrics['trading_days']}")
        report.append("")
        
        report.append("=" * 80)
        
        return "\n".join(report)
