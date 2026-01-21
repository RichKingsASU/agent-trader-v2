"""
Sector Rotation Strategy

A momentum-based sector rotation strategy that:
1. Ranks sector ETFs by recent performance (e.g., 20-day momentum)
2. Allocates capital to the top-performing sectors
3. Switches to cash (SHV) during market crashes (detected via broad market decline)
4. Rebalances periodically to maintain optimal allocation

This strategy is designed to capture sector-specific trends while preserving
capital during market downturns.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from functions.strategies.base_strategy import BaseStrategy, TradingSignal, SignalType

logger = logging.getLogger(__name__)


class SectorRotationStrategy(BaseStrategy):
    """
    Momentum-based sector rotation strategy with crash protection.
    
    Configuration parameters:
        - lookback_days: Number of days for momentum calculation (default: 20)
        - num_top_sectors: Number of top sectors to hold (default: 3)
        - crash_threshold: Market decline threshold to trigger cash (default: -0.05)
        - rebalance_frequency_days: Days between rebalancing (default: 5)
        - min_momentum: Minimum momentum to hold sector (default: 0.0)
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the Sector Rotation Strategy."""
        super().__init__(config)
        
        # Strategy parameters
        self.lookback_days = self.config.get("lookback_days", 20)
        self.num_top_sectors = self.config.get("num_top_sectors", 3)
        self.crash_threshold = self.config.get("crash_threshold", -0.05)
        self.rebalance_frequency_days = self.config.get("rebalance_frequency_days", 5)
        self.min_momentum = self.config.get("min_momentum", 0.0)
        
        # Sector universe
        self.sector_etfs = [
            "XLK",   # Technology
            "XLE",   # Energy
            "XLF",   # Financials
            "XLV",   # Healthcare
            "XLY",   # Consumer Discretionary
            "XLP",   # Consumer Staples
            "XLI",   # Industrials
            "XLB",   # Materials
            "XLU",   # Utilities
            "XLRE",  # Real Estate
        ]
        
        # Safe haven assets
        self.safe_haven = "SHV"  # Short-term Treasury ETF
        self.market_index = "SPY"  # Broad market index for crash detection
        
        # State tracking
        self.last_rebalance_date: Optional[datetime] = None
        self.price_history: Dict[str, List[Tuple[datetime, float]]] = {}
        self.current_holdings: List[str] = []
    
    def evaluate(
        self,
        market_data: Dict[str, Any],
        account_snapshot: Dict[str, Any],
        regime: Optional[str] = None
    ) -> TradingSignal:
        """
        Evaluate market conditions and generate trading signal.
        
        Args:
            market_data: Dictionary with price data for all symbols
            account_snapshot: Current account state
            regime: Market regime (LONG_GAMMA, SHORT_GAMMA, NEUTRAL)
            
        Returns:
            TradingSignal with rebalancing instructions
        """
        try:
            # Extract current timestamp
            current_time = datetime.utcnow()
            
            # Update price history
            self._update_price_history(market_data, current_time)
            
            # Check if we should rebalance
            if not self._should_rebalance(current_time):
                return TradingSignal(
                    signal_type=SignalType.HOLD,
                    symbol=self.market_index,
                    confidence=1.0,
                    reasoning="Not time to rebalance yet",
                    metadata={}
                )
            
            # Check for market crash
            if self._is_market_crash(market_data, regime):
                return self._generate_crash_signal()
            
            # Calculate momentum for each sector
            sector_momentum = self._calculate_sector_momentum(market_data)
            
            # Rank sectors by momentum
            ranked_sectors = self._rank_sectors(sector_momentum)
            
            # Select top sectors
            selected_sectors = self._select_top_sectors(ranked_sectors)
            
            # Generate rebalancing signal
            signal = self._generate_rebalancing_signal(
                selected_sectors,
                account_snapshot,
                sector_momentum
            )
            
            # Update state
            self.last_rebalance_date = current_time
            self.current_holdings = selected_sectors
            
            return signal
        
        except Exception as e:
            logger.exception(f"Error in SectorRotationStrategy.evaluate: {e}")
            return TradingSignal(
                signal_type=SignalType.HOLD,
                symbol=self.market_index,
                confidence=0.0,
                reasoning=f"Strategy error: {str(e)}",
                metadata={"error": str(e)}
            )
    
    def _update_price_history(
        self,
        market_data: Dict[str, Any],
        current_time: datetime
    ) -> None:
        """Update internal price history with current data."""
        for symbol, data in market_data.items():
            price = data.get("price")
            if price is not None:
                if symbol not in self.price_history:
                    self.price_history[symbol] = []
                
                self.price_history[symbol].append((current_time, float(price)))
                
                # Keep only recent history (2x lookback for momentum calculation)
                max_history = self.lookback_days * 2
                if len(self.price_history[symbol]) > max_history:
                    self.price_history[symbol] = self.price_history[symbol][-max_history:]
    
    def _should_rebalance(self, current_time: datetime) -> bool:
        """Determine if it's time to rebalance."""
        if self.last_rebalance_date is None:
            return True
        
        days_since_rebalance = (current_time - self.last_rebalance_date).days
        return days_since_rebalance >= self.rebalance_frequency_days
    
    def _is_market_crash(
        self,
        market_data: Dict[str, Any],
        regime: Optional[str]
    ) -> bool:
        """
        Detect if market is crashing.
        
        Conditions for crash:
        1. SPY is down more than crash_threshold
        2. OR regime is SHORT_GAMMA and multiple sectors are red
        """
        # Check SPY performance
        spy_data = market_data.get(self.market_index)
        if spy_data:
            price = spy_data.get("price")
            prev_price = spy_data.get("previous_price")
            
            if price and prev_price and prev_price > 0:
                spy_return = (price - prev_price) / prev_price
                if spy_return < self.crash_threshold:
                    logger.info(f"Market crash detected: SPY return = {spy_return:.2%}")
                    return True
        
        # Check if regime is SHORT_GAMMA and sectors are broadly negative
        if regime == "SHORT_GAMMA":
            # Count how many sectors are down
            negative_sectors = 0
            total_sectors = 0
            
            for sector in self.sector_etfs:
                sector_data = market_data.get(sector)
                if sector_data:
                    price = sector_data.get("price")
                    prev_price = sector_data.get("previous_price")
                    
                    if price and prev_price and prev_price > 0:
                        total_sectors += 1
                        sector_return = (price - prev_price) / prev_price
                        if sector_return < 0:
                            negative_sectors += 1
            
            # If 70%+ of sectors are negative in SHORT_GAMMA regime, it's a crash
            if total_sectors > 0 and negative_sectors / total_sectors > 0.7:
                logger.info(f"Crash detected: {negative_sectors}/{total_sectors} sectors negative in SHORT_GAMMA")
                return True
        
        return False
    
    def _generate_crash_signal(self) -> TradingSignal:
        """Generate signal to move to cash during crash."""
        return TradingSignal(
            signal_type=SignalType.CLOSE_ALL,
            symbol=self.market_index,
            confidence=1.0,
            reasoning=(
                f"Market crash detected (SPY decline > {self.crash_threshold:.1%}). "
                "Rotating to cash (SHV) to preserve capital."
            ),
            metadata={
                "target_symbol": self.safe_haven,
                "allocation": 1.0,  # 100% cash
                "reason": "crash_protection"
            }
        )
    
    def _calculate_sector_momentum(
        self,
        market_data: Dict[str, Any]
    ) -> Dict[str, float]:
        """
        Calculate momentum for each sector.
        
        Momentum = (Current Price - Price N days ago) / Price N days ago
        """
        sector_momentum = {}
        
        for sector in self.sector_etfs:
            if sector not in self.price_history or len(self.price_history[sector]) < 2:
                sector_momentum[sector] = 0.0
                continue
            
            # Get current and historical prices
            history = self.price_history[sector]
            current_price = history[-1][1]
            
            # Find price from lookback_days ago
            lookback_price = None
            current_time = history[-1][0]
            
            for timestamp, price in reversed(history[:-1]):
                days_diff = (current_time - timestamp).days
                if days_diff >= self.lookback_days:
                    lookback_price = price
                    break
            
            if lookback_price and lookback_price > 0:
                momentum = (current_price - lookback_price) / lookback_price
                sector_momentum[sector] = momentum
            else:
                sector_momentum[sector] = 0.0
        
        return sector_momentum
    
    def _rank_sectors(
        self,
        sector_momentum: Dict[str, float]
    ) -> List[Tuple[str, float]]:
        """
        Rank sectors by momentum (highest to lowest).
        
        Returns:
            List of (sector, momentum) tuples sorted by momentum descending
        """
        return sorted(
            sector_momentum.items(),
            key=lambda x: x[1],
            reverse=True
        )
    
    def _select_top_sectors(
        self,
        ranked_sectors: List[Tuple[str, float]]
    ) -> List[str]:
        """
        Select top N sectors with positive momentum.
        
        Only select sectors with momentum > min_momentum.
        If fewer than num_top_sectors have positive momentum, allocate to cash.
        """
        selected = []
        
        for sector, momentum in ranked_sectors:
            if momentum >= self.min_momentum and len(selected) < self.num_top_sectors:
                selected.append(sector)
        
        # If no sectors have positive momentum, go to cash
        if len(selected) == 0:
            logger.info("No sectors with positive momentum, rotating to cash")
            return [self.safe_haven]
        
        return selected
    
    def _generate_rebalancing_signal(
        self,
        selected_sectors: List[str],
        account_snapshot: Dict[str, Any],
        sector_momentum: Dict[str, float]
    ) -> TradingSignal:
        """
        Generate signal to rebalance portfolio to selected sectors.
        
        Equal-weight allocation across selected sectors.
        """
        num_sectors = len(selected_sectors)
        
        if num_sectors == 0:
            return TradingSignal(
                signal_type=SignalType.HOLD,
                symbol=self.market_index,
                confidence=0.0,
                reasoning="No sectors selected",
                metadata={}
            )
        
        # Equal weight allocation
        allocation_per_sector = 1.0 / num_sectors
        
        # Build target allocation
        target_allocation = {
            sector: allocation_per_sector
            for sector in selected_sectors
        }
        
        # Determine primary action
        if self.safe_haven in selected_sectors:
            signal_type = SignalType.CLOSE_ALL
            reasoning = "Low momentum across all sectors. Moving to cash (SHV)."
        else:
            signal_type = SignalType.BUY
            momentum_str = ", ".join([
                f"{sector}: {sector_momentum.get(sector, 0):.2%}"
                for sector in selected_sectors
            ])
            reasoning = (
                f"Rotating to top {num_sectors} momentum sectors: {', '.join(selected_sectors)}. "
                f"Momentum: {momentum_str}"
            )
        
        # Calculate confidence based on momentum strength
        avg_momentum = sum(sector_momentum.get(s, 0) for s in selected_sectors) / num_sectors
        confidence = min(1.0, max(0.0, 0.5 + avg_momentum * 2))  # Scale momentum to 0-1
        
        return TradingSignal(
            signal_type=signal_type,
            symbol=self.market_index,
            confidence=confidence,
            reasoning=reasoning,
            metadata={
                "target_allocation": target_allocation,
                "selected_sectors": selected_sectors,
                "sector_momentum": {
                    sector: sector_momentum.get(sector, 0)
                    for sector in selected_sectors
                },
                "rebalance_type": "sector_rotation"
            }
        )
