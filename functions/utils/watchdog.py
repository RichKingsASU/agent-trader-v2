"""
Operational Watchdog Agent: Anomaly Detection & Automatic Kill-Switch

This module monitors shadow trade history for anomalous behavior patterns and automatically
shuts down trading if dangerous patterns are detected.

Key Features:
- Real-time anomaly detection (e.g., 5 losing trades in a row within 10 minutes)
- Automatic kill-switch activation (sets trading_enabled = false)
- High-priority alerts to user dashboard
- AI-powered explainability using Gemini (Vertex AI)
- Multi-tenant support (per-user monitoring)

Architecture:
- Runs every minute via Cloud Scheduler
- Monitors users/{userId}/shadowTradeHistory for each active user
- Writes alerts to users/{userId}/alerts/{alertId}
- Updates users/{userId}/status/trading when kill-switch is triggered
- Logs explainability to users/{userId}/watchdog_events/{eventId}
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from google.cloud import firestore
try:
    import vertexai  # type: ignore
    from vertexai.generative_models import GenerativeModel  # type: ignore
except Exception:  # noqa: BLE001
    # Keep module import-safe in environments that don't install Vertex AI deps (e.g. unit-test CI).
    vertexai = None  # type: ignore[assignment]
    GenerativeModel = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Anomaly detection thresholds (configurable)
LOSING_STREAK_THRESHOLD = 5  # Number of consecutive losing trades
LOSING_STREAK_TIME_WINDOW_MINUTES = 10  # Time window to check for losing streaks
MIN_LOSS_PERCENT = Decimal("0.5")  # Minimum loss % to count as "losing trade" (0.5% = 50 bps)
RAPID_DRAWDOWN_THRESHOLD = Decimal("5.0")  # Drawdown % in time window to trigger alert


@dataclass
class AnomalyDetectionResult:
    """
    Result of anomaly detection analysis.
    
    Attributes:
        anomaly_detected: Whether an anomaly was found
        anomaly_type: Type of anomaly (e.g., "LOSING_STREAK", "RAPID_DRAWDOWN")
        severity: Severity level ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        description: Human-readable description
        metadata: Additional context (trade IDs, timestamps, etc.)
        should_halt_trading: Whether to activate kill-switch
    """
    anomaly_detected: bool
    anomaly_type: Optional[str] = None
    severity: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    should_halt_trading: bool = False


def _as_decimal(value: Any) -> Decimal:
    """Safely convert value to Decimal."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return Decimal("0")
        return Decimal(s)
    return Decimal("0")


def _get_recent_trades(
    db: firestore.Client,
    user_id: str,
    time_window_minutes: int = 10
) -> List[Dict[str, Any]]:
    """
    Get recent shadow trades for a user within the specified time window.
    
    Args:
        db: Firestore client
        user_id: User ID to query
        time_window_minutes: Time window in minutes (default: 10)
    
    Returns:
        List of trade dictionaries sorted by created_at (newest first)
    """
    try:
        # Calculate cutoff time
        cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)
        
        # Query recent trades
        trades_ref = (
            db.collection("users")
            .document(user_id)
            .collection("shadowTradeHistory")
            .where("created_at", ">=", cutoff_time)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(100)  # Safety limit
        )
        
        trades = []
        for doc in trades_ref.stream():
            trade_data = doc.to_dict()
            trade_data["id"] = doc.id
            trades.append(trade_data)
        
        return trades
    
    except Exception as e:
        logger.error(f"Error fetching recent trades for user {user_id}: {e}")
        return []


def _detect_losing_streak(
    trades: List[Dict[str, Any]],
    streak_threshold: int = LOSING_STREAK_THRESHOLD,
    min_loss_percent: Decimal = MIN_LOSS_PERCENT
) -> AnomalyDetectionResult:
    """
    Detect consecutive losing trades within the trade list.
    
    A trade is considered "losing" if:
    - Status is "CLOSED" with negative P&L
    - Status is "OPEN" with unrealized P&L < -0.5%
    
    Args:
        trades: List of trade dictionaries (sorted newest first)
        streak_threshold: Number of consecutive losses to trigger alert (default: 5)
        min_loss_percent: Minimum loss % to count as losing (default: 0.5%)
    
    Returns:
        AnomalyDetectionResult
    """
    if not trades or len(trades) < streak_threshold:
        return AnomalyDetectionResult(anomaly_detected=False)
    
    consecutive_losses = 0
    losing_trade_ids = []
    total_loss = Decimal("0")
    
    for trade in trades:
        # Get P&L data
        pnl_percent_str = trade.get("pnl_percent", "0")
        pnl_percent = _as_decimal(pnl_percent_str)
        
        # Check if trade is losing (negative P&L beyond threshold)
        if pnl_percent < -min_loss_percent:
            consecutive_losses += 1
            losing_trade_ids.append(trade.get("id", "unknown"))
            
            # Accumulate total loss
            current_pnl = _as_decimal(trade.get("current_pnl", "0"))
            total_loss += current_pnl
            
            # Check if we've hit the threshold
            if consecutive_losses >= streak_threshold:
                return AnomalyDetectionResult(
                    anomaly_detected=True,
                    anomaly_type="LOSING_STREAK",
                    severity="CRITICAL",
                    description=(
                        f"Detected {consecutive_losses} consecutive losing trades within "
                        f"{LOSING_STREAK_TIME_WINDOW_MINUTES} minutes. "
                        f"Total loss: ${abs(total_loss):.2f}"
                    ),
                    metadata={
                        "consecutive_losses": consecutive_losses,
                        "losing_trade_ids": losing_trade_ids,
                        "total_loss_usd": str(abs(total_loss)),
                        "time_window_minutes": LOSING_STREAK_TIME_WINDOW_MINUTES,
                    },
                    should_halt_trading=True
                )
        else:
            # Streak broken by a winning or neutral trade
            break
    
    return AnomalyDetectionResult(anomaly_detected=False)


def _detect_rapid_drawdown(
    trades: List[Dict[str, Any]],
    drawdown_threshold: Decimal = RAPID_DRAWDOWN_THRESHOLD
) -> AnomalyDetectionResult:
    """
    Detect rapid drawdown across recent trades.
    
    Calculates aggregate P&L across all trades in the time window and checks
    if total loss exceeds threshold.
    
    Args:
        trades: List of trade dictionaries
        drawdown_threshold: Drawdown % threshold (default: 5.0%)
    
    Returns:
        AnomalyDetectionResult
    """
    if not trades:
        return AnomalyDetectionResult(anomaly_detected=False)
    
    # Calculate aggregate P&L
    total_pnl = Decimal("0")
    total_cost_basis = Decimal("0")
    losing_trades = []
    
    for trade in trades:
        current_pnl = _as_decimal(trade.get("current_pnl", "0"))
        entry_price = _as_decimal(trade.get("entry_price", "0"))
        quantity = _as_decimal(trade.get("quantity", "0"))
        
        total_pnl += current_pnl
        total_cost_basis += entry_price * quantity
        
        if current_pnl < 0:
            losing_trades.append({
                "id": trade.get("id", "unknown"),
                "symbol": trade.get("symbol", "UNKNOWN"),
                "pnl": str(current_pnl),
                "pnl_percent": trade.get("pnl_percent", "0"),
            })
    
    # Calculate aggregate drawdown percentage
    if total_cost_basis > 0:
        drawdown_percent = (abs(total_pnl) / total_cost_basis) * Decimal("100")
    else:
        drawdown_percent = Decimal("0")
    
    # Check if drawdown exceeds threshold
    if total_pnl < 0 and drawdown_percent >= drawdown_threshold:
        return AnomalyDetectionResult(
            anomaly_detected=True,
            anomaly_type="RAPID_DRAWDOWN",
            severity="HIGH",
            description=(
                f"Rapid drawdown detected: {drawdown_percent:.2f}% loss "
                f"(${abs(total_pnl):.2f}) across {len(trades)} trades within "
                f"{LOSING_STREAK_TIME_WINDOW_MINUTES} minutes"
            ),
            metadata={
                "total_pnl_usd": str(total_pnl),
                "drawdown_percent": str(drawdown_percent),
                "total_cost_basis": str(total_cost_basis),
                "losing_trades_count": len(losing_trades),
                "losing_trades": losing_trades[:10],  # Limit to first 10
                "time_window_minutes": LOSING_STREAK_TIME_WINDOW_MINUTES,
            },
            should_halt_trading=(drawdown_percent >= drawdown_threshold)
        )
    
    return AnomalyDetectionResult(anomaly_detected=False)


def _detect_market_condition_mismatch(
    trades: List[Dict[str, Any]],
    db: firestore.Client
) -> AnomalyDetectionResult:
    """
    Detect if strategy is trading against market conditions.
    
    Example: Strategy keeps buying during a -2.5% market slide.
    
    Args:
        trades: List of trade dictionaries
        db: Firestore client to fetch market regime
    
    Returns:
        AnomalyDetectionResult
    """
    if not trades:
        return AnomalyDetectionResult(anomaly_detected=False)
    
    try:
        # Get current market regime
        regime_doc = db.collection("systemStatus").document("market_regime").get()
        
        if not regime_doc.exists:
            logger.warning("Market regime not found, skipping condition mismatch check")
            return AnomalyDetectionResult(anomaly_detected=False)
        
        regime_data = regime_doc.to_dict() or {}
        spy_gex = _as_decimal(regime_data.get("spy", {}).get("net_gex", "0"))
        market_bias = regime_data.get("market_volatility_bias", "Unknown")
        
        # Count recent BUY actions during negative GEX (bearish regime)
        buy_count = 0
        buy_trades = []
        
        for trade in trades[:10]:  # Check last 10 trades
            if trade.get("action") == "BUY" or trade.get("side") == "BUY":
                buy_count += 1
                buy_trades.append({
                    "id": trade.get("id", "unknown"),
                    "symbol": trade.get("symbol", "UNKNOWN"),
                    "action": trade.get("action", "UNKNOWN"),
                })
        
        # Anomaly: Multiple BUY trades during bearish market (negative GEX)
        if spy_gex < 0 and buy_count >= 3:
            return AnomalyDetectionResult(
                anomaly_detected=True,
                anomaly_type="MARKET_CONDITION_MISMATCH",
                severity="MEDIUM",
                description=(
                    f"Strategy executing {buy_count} BUY trades during bearish market "
                    f"(Negative GEX = ${spy_gex:,.0f}, bias={market_bias}). "
                    "This may indicate strategy is fighting market conditions."
                ),
                metadata={
                    "buy_count": buy_count,
                    "buy_trades": buy_trades,
                    "spy_net_gex": str(spy_gex),
                    "market_bias": market_bias,
                },
                should_halt_trading=False  # Warning only, don't halt
            )
        
        return AnomalyDetectionResult(anomaly_detected=False)
    
    except Exception as e:
        logger.error(f"Error in market condition mismatch detection: {e}")
        return AnomalyDetectionResult(anomaly_detected=False)


async def _generate_explainability_with_gemini(
    anomaly: AnomalyDetectionResult,
    trades: List[Dict[str, Any]],
    user_id: str,
    market_data: Optional[Dict[str, Any]] = None
) -> str:
    """
    Generate explainability log using Gemini (Vertex AI).
    
    Provides human-readable explanation of why the watchdog shut down trading.
    
    Args:
        anomaly: Detected anomaly result
        trades: Recent trades that triggered the anomaly
        user_id: User ID (for logging context)
        market_data: Optional market regime data
    
    Returns:
        Explainability string from Gemini
    """
    try:
        if vertexai is None or GenerativeModel is None:
            logger.warning("Vertex AI dependencies unavailable; using fallback explainability")
            return _generate_fallback_explanation(anomaly, trades, market_data)

        # Initialize Vertex AI
        import os
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
        location = os.environ.get("VERTEX_AI_LOCATION", "us-central1")
        
        if not project_id:
            logger.warning("Vertex AI project ID not configured, using fallback explanation")
            return _generate_fallback_explanation(anomaly, trades, market_data)
        
        vertexai.init(project=project_id, location=location)
        
        # Build prompt for Gemini
        prompt = _build_explainability_prompt(anomaly, trades, market_data)
        
        # Call Gemini
        model = GenerativeModel("gemini-2.0-flash-exp")
        response = model.generate_content(prompt)
        
        explanation = response.text.strip()
        
        logger.info(f"Generated explainability for user {user_id}: {explanation[:200]}...")
        
        return explanation
    
    except Exception as e:
        logger.error(f"Error generating explainability with Gemini: {e}")
        return _generate_fallback_explanation(anomaly, trades, market_data)


def _build_explainability_prompt(
    anomaly: AnomalyDetectionResult,
    trades: List[Dict[str, Any]],
    market_data: Optional[Dict[str, Any]] = None
) -> str:
    """Build prompt for Gemini to generate explainability."""
    
    # Summarize recent trades
    trades_summary = []
    for i, trade in enumerate(trades[:10], 1):
        symbol = trade.get("symbol", "UNKNOWN")
        action = trade.get("action", "UNKNOWN")
        pnl_percent = trade.get("pnl_percent", "0")
        reasoning = trade.get("reasoning", "No reasoning provided")[:100]
        
        trades_summary.append(
            f"{i}. {action} {symbol} - P&L: {pnl_percent}% - Reasoning: {reasoning}"
        )
    
    # Market context
    market_context = "Market data unavailable"
    if market_data:
        spy_gex = market_data.get("spy", {}).get("net_gex", "Unknown")
        market_bias = market_data.get("market_volatility_bias", "Unknown")
        market_context = f"SPY Net GEX: {spy_gex}, Market Bias: {market_bias}"
    
    prompt = f"""You are an AI trading risk analyst. Explain why the automated watchdog system shut down trading.

**Anomaly Detected:**
- Type: {anomaly.anomaly_type}
- Severity: {anomaly.severity}
- Description: {anomaly.description}

**Recent Trades (Last {LOSING_STREAK_TIME_WINDOW_MINUTES} minutes):**
{chr(10).join(trades_summary)}

**Market Context:**
{market_context}

**Task:**
Write a clear, concise explanation (2-3 sentences) for the user's dashboard explaining:
1. What pattern triggered the shutdown
2. Why this pattern is dangerous
3. What market conditions (if any) contributed to the issue

Keep it professional but urgent. Start with "Agent shut down because..."
"""
    
    return prompt


def _generate_fallback_explanation(
    anomaly: AnomalyDetectionResult,
    trades: List[Dict[str, Any]],
    market_data: Optional[Dict[str, Any]] = None
) -> str:
    """Generate fallback explanation if Gemini is unavailable."""
    
    explanation = f"Agent shut down because {anomaly.description}"
    
    # Add market context if available
    if market_data:
        market_bias = market_data.get("market_volatility_bias", "Unknown")
        spy_gex = market_data.get("spy", {}).get("net_gex", "Unknown")
        
        if market_bias == "Bearish":
            explanation += f" This occurred during a bearish market regime (Negative GEX = {spy_gex})."
        elif market_bias == "Bullish":
            explanation += f" Market conditions were bullish (Positive GEX = {spy_gex}), suggesting strategy malfunction."
    
    # Add losing trades context
    losing_trades = [t for t in trades if _as_decimal(t.get("pnl_percent", "0")) < 0]
    if losing_trades:
        total_loss = sum(_as_decimal(t.get("current_pnl", "0")) for t in losing_trades)
        explanation += f" Total loss: ${abs(total_loss):.2f} across {len(losing_trades)} trades."
    
    return explanation


def _activate_kill_switch(
    db: firestore.Client,
    user_id: str,
    anomaly: AnomalyDetectionResult,
    explanation: str
) -> Dict[str, Any]:
    """
    Activate kill-switch for user: set trading_enabled = false.
    
    Args:
        db: Firestore client
        user_id: User ID to disable trading for
        anomaly: Detected anomaly
        explanation: AI-generated explanation
    
    Returns:
        Dictionary with kill-switch activation details
    """
    try:
        logger.warning(f"🚨 KILL-SWITCH ACTIVATED for user {user_id}: {anomaly.anomaly_type}")
        
        # Update user's trading status
        status_ref = (
            db.collection("users")
            .document(user_id)
            .collection("status")
            .document("trading")
        )
        
        status_ref.set({
            "enabled": False,
            "disabled_by": "watchdog",
            "disabled_at": firestore.SERVER_TIMESTAMP,
            "reason": anomaly.description,
            "anomaly_type": anomaly.anomaly_type,
            "severity": anomaly.severity,
            "explanation": explanation,
        }, merge=True)
        
        logger.info(f"User {user_id}: Trading disabled successfully")
        
        return {
            "success": True,
            "user_id": user_id,
            "trading_enabled": False,
            "reason": anomaly.description,
            "explanation": explanation,
        }
    
    except Exception as e:
        logger.error(f"Error activating kill-switch for user {user_id}: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def _send_high_priority_alert(
    db: firestore.Client,
    user_id: str,
    anomaly: AnomalyDetectionResult,
    explanation: str
) -> str:
    """
    Send high-priority alert to user's dashboard.
    
    Creates an alert document at users/{userId}/alerts/{alertId}.
    
    Args:
        db: Firestore client
        user_id: User ID to send alert to
        anomaly: Detected anomaly
        explanation: AI-generated explanation
    
    Returns:
        Alert document ID
    """
    try:
        alert_data = {
            "type": "WATCHDOG_KILL_SWITCH",
            "severity": anomaly.severity,
            "title": f"Trading Halted: {anomaly.anomaly_type}",
            "message": explanation,
            "anomaly_type": anomaly.anomaly_type,
            "anomaly_description": anomaly.description,
            "metadata": anomaly.metadata or {},
            "created_at": firestore.SERVER_TIMESTAMP,
            "read": False,
            "acknowledged": False,
            "priority": "HIGH",
        }
        
        # Create alert document
        alert_ref = (
            db.collection("users")
            .document(user_id)
            .collection("alerts")
            .add(alert_data)
        )
        
        alert_id = alert_ref[1].id
        
        logger.info(f"High-priority alert sent to user {user_id}: {alert_id}")
        
        return alert_id
    
    except Exception as e:
        logger.error(f"Error sending alert to user {user_id}: {e}")
        return ""


def _log_watchdog_event(
    db: firestore.Client,
    user_id: str,
    anomaly: AnomalyDetectionResult,
    explanation: str,
    kill_switch_activated: bool
) -> str:
    """
    Log watchdog event for audit trail and analysis.
    
    Creates event document at users/{userId}/watchdog_events/{eventId}.
    
    Args:
        db: Firestore client
        user_id: User ID
        anomaly: Detected anomaly
        explanation: AI-generated explanation
        kill_switch_activated: Whether kill-switch was activated
    
    Returns:
        Event document ID
    """
    try:
        event_data = {
            "user_id": user_id,
            "anomaly_detected": anomaly.anomaly_detected,
            "anomaly_type": anomaly.anomaly_type,
            "severity": anomaly.severity,
            "description": anomaly.description,
            "explanation": explanation,
            "metadata": anomaly.metadata or {},
            "kill_switch_activated": kill_switch_activated,
            "timestamp": firestore.SERVER_TIMESTAMP,
        }
        
        # Create event document
        event_ref = (
            db.collection("users")
            .document(user_id)
            .collection("watchdog_events")
            .add(event_data)
        )
        
        event_id = event_ref[1].id
        
        logger.info(f"Watchdog event logged for user {user_id}: {event_id}")
        
        return event_id
    
    except Exception as e:
        logger.error(f"Error logging watchdog event for user {user_id}: {e}")
        return ""


async def monitor_user_trades(
    db: firestore.Client,
    user_id: str
) -> Dict[str, Any]:
    """
    Monitor shadow trades for a single user and detect anomalies.
    
    This is the main entry point for per-user watchdog monitoring.
    
    Args:
        db: Firestore client
        user_id: User ID to monitor
    
    Returns:
        Dictionary with monitoring results
    """
    try:
        logger.info(f"Monitoring user {user_id} for anomalous trading behavior...")
        
        # Check if trading is already disabled
        status_ref = (
            db.collection("users")
            .document(user_id)
            .collection("status")
            .document("trading")
        )
        status_doc = status_ref.get()
        
        if status_doc.exists:
            status_data = status_doc.to_dict() or {}
            if not status_data.get("enabled", True):
                logger.info(f"User {user_id}: Trading already disabled, skipping monitoring")
                return {
                    "user_id": user_id,
                    "status": "ALREADY_DISABLED",
                    "message": "Trading already disabled for this user",
                }
        
        # Get recent trades
        trades = _get_recent_trades(
            db=db,
            user_id=user_id,
            time_window_minutes=LOSING_STREAK_TIME_WINDOW_MINUTES
        )
        
        if not trades:
            logger.debug(f"User {user_id}: No recent trades to monitor")
            return {
                "user_id": user_id,
                "status": "NO_TRADES",
                "message": "No recent trades found",
            }
        
        logger.info(f"User {user_id}: Analyzing {len(trades)} recent trades...")
        
        # Run anomaly detection checks
        losing_streak = _detect_losing_streak(trades)
        rapid_drawdown = _detect_rapid_drawdown(trades)
        condition_mismatch = _detect_market_condition_mismatch(trades, db)
        
        # Determine if any critical anomaly was detected
        anomalies = [
            losing_streak,
            rapid_drawdown,
            condition_mismatch,
        ]
        
        critical_anomaly = None
        for anomaly in anomalies:
            if anomaly.anomaly_detected and anomaly.should_halt_trading:
                critical_anomaly = anomaly
                break
        
        # If critical anomaly detected, activate kill-switch
        if critical_anomaly:
            logger.warning(
                f"User {user_id}: CRITICAL ANOMALY DETECTED - {critical_anomaly.anomaly_type}"
            )
            
            # Get market data for context
            market_data = None
            try:
                regime_doc = db.collection("systemStatus").document("market_regime").get()
                if regime_doc.exists:
                    market_data = regime_doc.to_dict()
            except Exception as e:
                logger.warning(f"Failed to fetch market data: {e}")
            
            # Generate explainability with Gemini
            explanation = await _generate_explainability_with_gemini(
                anomaly=critical_anomaly,
                trades=trades,
                user_id=user_id,
                market_data=market_data
            )
            
            # Activate kill-switch
            kill_switch_result = _activate_kill_switch(
                db=db,
                user_id=user_id,
                anomaly=critical_anomaly,
                explanation=explanation
            )
            
            # Send high-priority alert
            alert_id = _send_high_priority_alert(
                db=db,
                user_id=user_id,
                anomaly=critical_anomaly,
                explanation=explanation
            )
            
            # Log event for audit trail
            event_id = _log_watchdog_event(
                db=db,
                user_id=user_id,
                anomaly=critical_anomaly,
                explanation=explanation,
                kill_switch_activated=True
            )
            
            return {
                "user_id": user_id,
                "status": "KILL_SWITCH_ACTIVATED",
                "anomaly_type": critical_anomaly.anomaly_type,
                "severity": critical_anomaly.severity,
                "description": critical_anomaly.description,
                "explanation": explanation,
                "alert_id": alert_id,
                "event_id": event_id,
                "kill_switch_result": kill_switch_result,
            }
        
        # Log non-critical anomalies (warnings only)
        warnings = [a for a in anomalies if a.anomaly_detected and not a.should_halt_trading]
        if warnings:
            for warning in warnings:
                logger.info(
                    f"User {user_id}: Warning - {warning.anomaly_type}: {warning.description}"
                )
                
                # Log warning event (but don't halt trading)
                _log_watchdog_event(
                    db=db,
                    user_id=user_id,
                    anomaly=warning,
                    explanation=warning.description,
                    kill_switch_activated=False
                )
            
            return {
                "user_id": user_id,
                "status": "WARNINGS_DETECTED",
                "warnings": [
                    {
                        "type": w.anomaly_type,
                        "severity": w.severity,
                        "description": w.description,
                    }
                    for w in warnings
                ],
            }
        
        # All clear
        logger.debug(f"User {user_id}: No anomalies detected")
        return {
            "user_id": user_id,
            "status": "ALL_CLEAR",
            "message": "No anomalies detected",
            "trades_analyzed": len(trades),
        }
    
    except Exception as e:
        logger.exception(f"Error monitoring user {user_id}: {e}")
        return {
            "user_id": user_id,
            "status": "ERROR",
            "error": str(e),
        }


async def monitor_all_users(db: firestore.Client) -> Dict[str, Any]:
    """
    Monitor all active users for anomalous trading behavior.
    
    This is the main entry point for the scheduled watchdog function.
    
    Args:
        db: Firestore client
    
    Returns:
        Dictionary with aggregated monitoring results
    """
    logger.info("🔍 Operational Watchdog: Starting monitoring sweep...")
    
    try:
        # Query all users
        users_ref = db.collection("users")
        users = users_ref.stream()
        
        results = []
        kill_switches_activated = 0
        warnings_detected = 0
        errors = 0
        
        for user_doc in users:
            user_id = user_doc.id
            
            try:
                # Monitor this user
                result = await monitor_user_trades(db=db, user_id=user_id)
                results.append(result)
                
                # Track statistics
                if result["status"] == "KILL_SWITCH_ACTIVATED":
                    kill_switches_activated += 1
                elif result["status"] == "WARNINGS_DETECTED":
                    warnings_detected += 1
                elif result["status"] == "ERROR":
                    errors += 1
            
            except Exception as e:
                logger.error(f"Error monitoring user {user_id}: {e}")
                errors += 1
                results.append({
                    "user_id": user_id,
                    "status": "ERROR",
                    "error": str(e),
                })
        
        # Log summary
        logger.info(
            f"Watchdog sweep complete: {len(results)} users monitored, "
            f"{kill_switches_activated} kill-switches activated, "
            f"{warnings_detected} warnings, {errors} errors"
        )
        
        # Store global watchdog status
        try:
            watchdog_status_ref = db.collection("ops").document("watchdog_status")
            watchdog_status_ref.set({
                "last_sweep_at": firestore.SERVER_TIMESTAMP,
                "users_monitored": len(results),
                "kill_switches_activated": kill_switches_activated,
                "warnings_detected": warnings_detected,
                "errors": errors,
            }, merge=True)
        except Exception as e:
            logger.error(f"Failed to store watchdog status: {e}")
        
        return {
            "success": True,
            "users_monitored": len(results),
            "kill_switches_activated": kill_switches_activated,
            "warnings_detected": warnings_detected,
            "errors": errors,
            "results": results,
        }
    
    except Exception as e:
        logger.exception("Critical error in watchdog monitoring sweep")
        return {
            "success": False,
            "error": str(e),
        }
