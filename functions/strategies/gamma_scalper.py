"""
0DTE Gamma Scalper Strategy.

This strategy monitors Delta Drift and Gamma Exposure to profit from market maker
hedging flows. It implements:
1. Delta Hedge Rule: Rebalance when net delta exceeds threshold
2. GEX Filter: Adjust allocation based on gamma exposure
3. Time-Based Exit: Close all positions after 15:45 EST
"""

import logging
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Dict, List, Optional
import pytz

from .base_strategy import BaseStrategy, SignalType, TradingSignal

logger = logging.getLogger(__name__)


class GammaScalper(BaseStrategy):
    """
    0DTE Gamma Scalper Strategy.
    
    Monitors Delta Drift and Gamma Exposure to capitalize on market maker hedging flows.
    """
    
    # Default configuration
    DEFAULT_HEDGING_THRESHOLD = Decimal("0.15")
    MARKET_CLOSE_TIME = time(15, 45, 0)  # 15:45 EST
    EST_TIMEZONE = pytz.timezone("America/New_York")
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the Gamma Scalper strategy.
        
        Config parameters:
            threshold: Delta threshold for hedging (default: 0.15)
            gex_positive_multiplier: Allocation multiplier when GEX is positive (default: 0.5)
            gex_negative_multiplier: Allocation multiplier when GEX is negative (default: 1.5)
        """
        super().__init__(config)

        # Post-15:45 ET behavior:
        # - emit CLOSE_ALL once (if needed)
        # - then halt for the rest of the ET day (no further hedging)
        self._halted_day_et: Optional[date] = None
        self._close_emitted_day_et: Optional[date] = None
        
        # Set hedging threshold with Decimal precision
        threshold = self.config.get("threshold", self.DEFAULT_HEDGING_THRESHOLD)
        self.hedging_threshold = Decimal(str(threshold))
        
        # GEX multipliers
        self.gex_positive_multiplier = self.config.get("gex_positive_multiplier", 0.5)
        self.gex_negative_multiplier = self.config.get("gex_negative_multiplier", 1.5)
        
        logger.info(
            f"GammaScalper initialized: threshold={self.hedging_threshold}, "
            f"gex_pos_mult={self.gex_positive_multiplier}, "
            f"gex_neg_mult={self.gex_negative_multiplier}"
        )
    
    def evaluate(
        self,
        market_data: Dict[str, Any],
        account_snapshot: Dict[str, Any],
        regime: Optional[str] = None
    ) -> TradingSignal:
        """
        Evaluate market conditions and generate a trading signal.
        
        Logic:
        1. Check time-based exit (after 15:45 EST)
        2. Calculate net delta from positions
        3. Apply delta hedge rule
        4. Apply GEX filter to adjust allocation based on market regime
        
        Args:
            market_data: Contains price, greeks, and gex_status
            account_snapshot: Contains positions and account info
            regime: Market regime from GEX engine:
                - "LONG_GAMMA": Dampen allocation (stabilizing market)
                - "SHORT_GAMMA": Increase allocation (accelerating volatility)
                - "NEUTRAL" or None: Use neutral allocation
        
        Returns:
            TradingSignal with action, confidence, and reasoning
        """
        try:
            # Step 1: Time-Based Exit Rule
            now_et = datetime.now(self.EST_TIMEZONE)
            current_day_et = now_et.date()
            current_time = now_et.time()

            # Day rollover: clear halt flags when ET date changes.
            if self._halted_day_et is not None and self._halted_day_et != current_day_et:
                self._halted_day_et = None
                self._close_emitted_day_et = None

            if current_time >= self.MARKET_CLOSE_TIME:
                # Already halted for this ET day: do nothing further.
                if self._halted_day_et == current_day_et:
                    signal = TradingSignal(
                        signal_type=SignalType.HOLD,
                        confidence=0.0,
                        reasoning=(
                            f"Post-close halt: Current time {current_time.strftime('%H:%M:%S')} "
                            f"is past {self.MARKET_CLOSE_TIME.strftime('%H:%M:%S')} ET. "
                            "Strategy halted for the rest of the day (no hedging)."
                        ),
                        metadata={
                            "current_time": current_time.isoformat(),
                            "close_time": self.MARKET_CLOSE_TIME.isoformat(),
                            "halted_for_day": True,
                        }
                    )
                    return self.sign_signal(signal)

                # First observation at/after close: halt for the rest of day.
                self._halted_day_et = current_day_et

                # Emit CLOSE_ALL once *only if needed* (positions exist).
                positions = account_snapshot.get("positions") or []
                if positions and self._close_emitted_day_et != current_day_et:
                    self._close_emitted_day_et = current_day_et
                    signal = TradingSignal(
                        signal_type=SignalType.CLOSE_ALL,
                        confidence=1.0,
                        reasoning=(
                            f"Time-based exit: Current time {current_time.strftime('%H:%M:%S')} "
                            f"is past market close threshold {self.MARKET_CLOSE_TIME.strftime('%H:%M:%S')} ET. "
                            "Closing all positions, then halting for the rest of the day."
                        ),
                        metadata={
                            "current_time": current_time.isoformat(),
                            "close_time": self.MARKET_CLOSE_TIME.isoformat(),
                            "halted_for_day": True,
                        }
                    )
                    return self.sign_signal(signal)

                # No positions to close: just halt.
                signal = TradingSignal(
                    signal_type=SignalType.HOLD,
                    confidence=0.0,
                    reasoning=(
                        f"Time-based exit: Current time {current_time.strftime('%H:%M:%S')} "
                        f"is past market close threshold {self.MARKET_CLOSE_TIME.strftime('%H:%M:%S')} ET. "
                        "No positions to close. Strategy halted for the rest of the day (no hedging)."
                    ),
                    metadata={
                        "current_time": current_time.isoformat(),
                        "close_time": self.MARKET_CLOSE_TIME.isoformat(),
                        "halted_for_day": True,
                    }
                )
                # Sign signal for Zero-Trust verification
                return self.sign_signal(signal)
            
            # Step 2: Calculate Net Delta
            net_delta = self._calculate_net_delta(account_snapshot, market_data)
            logger.info(f"Calculated net_delta: {net_delta}")
            
            # Step 3: Apply Delta Hedge Rule
            abs_delta = abs(net_delta)
            
            if abs_delta <= self.hedging_threshold:
                # Portfolio is delta neutral - no action needed
                signal = TradingSignal(
                    signal_type=SignalType.HOLD,
                    confidence=0.7,
                    reasoning=(
                        f"Portfolio is delta neutral. Net delta ({net_delta:.4f}) "
                        f"is within threshold (±{self.hedging_threshold}). No rebalancing needed."
                    ),
                    metadata={
                        "net_delta": float(net_delta),
                        "threshold": float(self.hedging_threshold),
                        "delta_status": "neutral"
                    }
                )
                return self.sign_signal(signal)
            
            # Portfolio needs rebalancing
            if net_delta < 0:
                # Under-hedged (negative delta) - BUY to increase delta
                base_signal = SignalType.BUY
                delta_status = "under_hedged"
                reasoning_prefix = (
                    f"Under-hedged position detected. Net delta ({net_delta:.4f}) "
                    f"is below threshold (-{self.hedging_threshold}). Buying to return to delta neutral."
                )
            else:
                # Over-hedged (positive delta) - SELL to decrease delta
                base_signal = SignalType.SELL
                delta_status = "over_hedged"
                reasoning_prefix = (
                    f"Over-hedged position detected. Net delta ({net_delta:.4f}) "
                    f"exceeds threshold (+{self.hedging_threshold}). Selling to return to delta neutral."
                )
            
            # Step 4: Apply GEX Filter
            # Prefer regime parameter over legacy gex_status in market_data
            if regime:
                gex_status = regime.lower()
            else:
                gex_status = market_data.get("gex_status", "unknown").lower()
            
            allocation_multiplier, gex_reasoning = self._apply_gex_filter(gex_status)
            
            # Calculate final confidence based on delta magnitude and GEX
            base_confidence = min(float(abs_delta) / float(self.hedging_threshold), 2.0) * 0.5
            final_confidence = min(base_confidence * allocation_multiplier, 1.0)
            
            signal = TradingSignal(
                signal_type=base_signal,
                confidence=final_confidence,
                reasoning=f"{reasoning_prefix} {gex_reasoning}",
                metadata={
                    "net_delta": float(net_delta),
                    "abs_delta": float(abs_delta),
                    "threshold": float(self.hedging_threshold),
                    "delta_status": delta_status,
                    "gex_status": gex_status,
                    "allocation_multiplier": allocation_multiplier,
                    "base_confidence": base_confidence,
                    "target_allocation": final_confidence * 100  # As percentage
                }
            )
            return self.sign_signal(signal)
            
        except Exception as e:
            logger.exception(f"Error in GammaScalper.evaluate: {e}")
            signal = TradingSignal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                reasoning=f"Error evaluating strategy: {str(e)}",
                metadata={"error": str(e)}
            )
            # Even error signals should be signed for audit trail
            try:
                return self.sign_signal(signal)
            except Exception:
                # If signing fails, return unsigned (last resort)
                return signal
    
    def _calculate_net_delta(
        self,
        account_snapshot: Dict[str, Any],
        market_data: Dict[str, Any]
    ) -> Decimal:
        """
        Calculate the net delta of the portfolio.
        
        Net Delta = Sum of (position_quantity * option_delta) for all positions
        
        Args:
            account_snapshot: Account information with positions
            market_data: Market data with current greeks
        
        Returns:
            Decimal: Net delta of the portfolio
        """
        positions = account_snapshot.get("positions", [])
        
        if not positions:
            # No positions means delta = 0
            return Decimal("0")
        
        net_delta = Decimal("0")
        
        for position in positions:
            try:
                qty = Decimal(str(position.get("qty", 0)))
                
                # Get delta from position's greeks or from market_data
                position_greeks = position.get("greeks", {})
                if position_greeks and "delta" in position_greeks:
                    delta = Decimal(str(position_greeks["delta"]))
                elif market_data.get("greeks") and "delta" in market_data["greeks"]:
                    # Fall back to current market delta if position delta not available
                    delta = Decimal(str(market_data["greeks"]["delta"]))
                else:
                    # If no delta available, skip this position
                    logger.warning(
                        f"No delta available for position {position.get('symbol')}. "
                        "Skipping in net delta calculation."
                    )
                    continue
                
                position_delta = qty * delta
                net_delta += position_delta
                
                logger.debug(
                    f"Position {position.get('symbol')}: qty={qty}, "
                    f"delta={delta}, position_delta={position_delta}"
                )
                
            except (ValueError, TypeError, KeyError) as e:
                logger.warning(f"Error processing position: {e}. Skipping.")
                continue
        
        return net_delta
    
    def _apply_gex_filter(self, gex_status: str) -> tuple[float, str]:
        """
        Apply GEX (Gamma Exposure) filter to adjust allocation.
        
        Market Regimes:
        - SHORT_GAMMA (Negative GEX): Market makers need to buy/sell more aggressively 
          to hedge, leading to increased volatility. INCREASE allocation.
        - LONG_GAMMA (Positive GEX): Market makers' hedging dampens price movements.
          DECREASE allocation.
        - NEUTRAL/UNKNOWN: Use neutral multiplier.
        
        This allows the strategy to automatically tighten hedging bands when GEX flips
        to negative (accelerating volatility regime).
        
        Args:
            gex_status: "long_gamma", "short_gamma", "neutral", "positive", "negative", or "unknown"
        
        Returns:
            Tuple of (allocation_multiplier, reasoning)
        """
        gex_lower = gex_status.lower()
        
        # Map regime names to behavior
        if gex_lower in ("short_gamma", "negative"):
            return (
                self.gex_negative_multiplier,
                f"Regime: SHORT_GAMMA (Net GEX < 0) - Accelerating volatility expected. "
                f"Market makers amplify price movements through hedging. "
                f"Increasing allocation by {self.gex_negative_multiplier}x to capitalize on volatility."
            )
        elif gex_lower in ("long_gamma", "positive"):
            return (
                self.gex_positive_multiplier,
                f"Regime: LONG_GAMMA (Net GEX > 0) - Price stabilization expected. "
                f"Market makers dampen price movements through hedging. "
                f"Decreasing allocation to {self.gex_positive_multiplier}x for conservative positioning."
            )
        else:
            # Neutral or unknown - use neutral multiplier
            return (
                1.0,
                f"Regime: {gex_status.upper()} - Using neutral allocation (1.0x)."
            )
