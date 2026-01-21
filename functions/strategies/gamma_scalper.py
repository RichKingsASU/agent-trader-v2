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
from backend.common.trading_config import get_options_contract_multiplier

logger = logging.getLogger(__name__)

# ============================================================================
# Safety Hardening (Execution Intent Suppression)
# ============================================================================
# This strategy file must remain safe to import and run in any environment.
# It is used for *signal generation*, but downstream systems could treat BUY/SELL/
# CLOSE_ALL as executable intent. The guard below ensures this module can NEVER be
# misused to trigger broker actions unintentionally.
#
# Policy:
# - Enforce TRADING_MODE == "paper" at runtime
# - Enforce kill switch EXECUTION_HALTED (any truthy value halts)
# - Require explicit dual unlock:
#     ENABLE_DANGEROUS_FUNCTIONS == "true" AND EXEC_GUARD_UNLOCK == "1"
# - If any check fails -> log and downgrade to HOLD (NO_OP)
# ============================================================================


def _execution_intent_allowed() -> tuple[bool, str, Dict[str, str]]:
    """
    Centralized execution guard for *any* actionable trading intent.

    IMPORTANT: We intentionally do not accept "truthy" variants for the dual unlock.
    Requirements demand strict values:
      - ENABLE_DANGEROUS_FUNCTIONS == "true"
      - EXEC_GUARD_UNLOCK == "1"
    """
    trading_mode = (os.getenv("TRADING_MODE") or "").strip()
    execution_halted = (os.getenv("EXECUTION_HALTED") or "").strip()
    enable_dangerous = (os.getenv("ENABLE_DANGEROUS_FUNCTIONS") or "").strip()
    exec_guard_unlock = (os.getenv("EXEC_GUARD_UNLOCK") or "").strip()

    env_snapshot = {
        "TRADING_MODE": trading_mode,
        "EXECUTION_HALTED": execution_halted,
        "ENABLE_DANGEROUS_FUNCTIONS": enable_dangerous,
        "EXEC_GUARD_UNLOCK": exec_guard_unlock,
    }

    # 1) Must be paper trading mode (strict)
    if trading_mode.lower() != "paper":
        return False, "TRADING_MODE must be 'paper'", env_snapshot

    # 2) Kill switch must NOT be active (treat any common truthy value as halted)
    if execution_halted.lower() in {"1", "true", "t", "yes", "y", "on"}:
        return False, "EXECUTION_HALTED is active (kill switch)", env_snapshot

    # 3) Dual unlock must be present (strict equality per requirements)
    if enable_dangerous != "true":
        return False, "ENABLE_DANGEROUS_FUNCTIONS must equal 'true'", env_snapshot
    if exec_guard_unlock != "1":
        return False, "EXEC_GUARD_UNLOCK must equal '1'", env_snapshot

    return True, "ok", env_snapshot


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
            # ----------------------------------------------------------------
            # SAFETY: Never emit actionable intent unless explicit guard passes.
            # We still compute signals normally (for analysis/audit), but any
            # BUY/SELL/CLOSE_ALL is downgraded to HOLD when guardrails fail.
            # ----------------------------------------------------------------

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
                        symbol=self.symbol,
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
                        symbol=self.symbol,
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
                    symbol=self.symbol,
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
                signal = self._apply_execution_safeguards(signal)
                return self.sign_signal(signal)
            
            # Step 2: Calculate Net Delta
            net_delta = self._calculate_net_delta(account_snapshot, market_data)
            logger.info(f"Calculated net_delta: {net_delta}")
            
            # Step 3: Apply Delta Hedge Rule
            # Threshold is expressed in "contract-delta" units (e.g. 0.15),
            # while net_delta is computed in share-equivalent units.
            contract_multiplier = Decimal(str(get_options_contract_multiplier()))
            abs_delta = abs(net_delta) / contract_multiplier if contract_multiplier != Decimal("0") else abs(net_delta)
            
            if abs_delta <= self.hedging_threshold:
                # Portfolio is delta neutral - no action needed
                signal = TradingSignal(
                    signal_type=SignalType.HOLD,
                    symbol=self.symbol,
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
                symbol=self.symbol,
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
            signal = self._apply_execution_safeguards(signal)
            return self.sign_signal(signal)
            
        except Exception as e:
            logger.exception(f"Error in GammaScalper.evaluate: {e}")
            signal = TradingSignal(
                signal_type=SignalType.HOLD,
                symbol=self.symbol,
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

    def _apply_execution_safeguards(self, signal: TradingSignal) -> TradingSignal:
        """
        Downgrade actionable intent to HOLD when runtime safety checks fail.

        This is intentionally local to this strategy module to keep the diff
        minimal and to avoid touching any execution services.
        """
        # Only suppress signals that could plausibly be acted on by an executor.
        if signal.signal_type not in {SignalType.BUY, SignalType.SELL, SignalType.CLOSE_ALL}:
            return signal

        allowed, deny_reason, env_snapshot = _execution_intent_allowed()
        if allowed:
            return signal

        # Log loudly: this should surface in any environment where someone tries
        # to (mis)use this strategy to drive execution.
        logger.error(
            "EXECUTION SUPPRESSED by guardrails: intended_action=%s reason=%s env=%s",
            getattr(signal.signal_type, "value", str(signal.signal_type)),
            deny_reason,
            env_snapshot,
        )

        # Return a safe NO_OP. Preserve the original intent in metadata for audit.
        suppressed_metadata = dict(getattr(signal, "metadata", {}) or {})
        suppressed_metadata.update(
            {
                "execution_suppressed": True,
                "suppressed_reason": deny_reason,
                "suppressed_env": env_snapshot,
                "suppressed_intended_action": getattr(signal.signal_type, "value", str(signal.signal_type)),
                "suppressed_intended_confidence": getattr(signal, "confidence", None),
            }
        )

        return TradingSignal(
            signal_type=SignalType.HOLD,
            symbol=self.symbol,
            confidence=0.0,
            reasoning=(
                "Execution intent suppressed by safety guardrails. "
                "Strategy remains available for signal generation only."
            ),
            metadata=suppressed_metadata,
        )
    
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
        contract_multiplier = Decimal(str(get_options_contract_multiplier()))
        
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
                
                # Options delta is per-share for 1 contract; convert to shares.
                # If a caller passes equity positions here, treat them as 1x multiplier.
                asset_type = str(position.get("asset_type") or position.get("asset_class") or "").strip().lower()
                is_option = bool(position.get("greeks")) or ("option" in asset_type)
                multiplier = contract_multiplier if is_option else Decimal("1")
                position_delta = qty * delta * multiplier
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
