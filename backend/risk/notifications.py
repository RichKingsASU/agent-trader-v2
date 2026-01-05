"""
Notification Service for Circuit Breaker Events.

This service handles sending notifications to users when circuit breakers
are triggered. Supports multiple channels:
- Firestore (in-app notifications)
- Email (future)
- SMS (future)
- Push notifications (future)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Service for sending notifications about circuit breaker events.
    
    Currently implements Firestore-based notifications that can be
    displayed in the web UI. Future enhancements can add email, SMS, etc.
    """
    
    def __init__(self, db_client: Any = None):
        """
        Initialize the notification service.
        
        Args:
            db_client: Firestore client for storing notifications
        """
        self.db = db_client
    
    async def send_notification(
        self,
        *,
        user_id: str,
        title: str,
        message: str,
        severity: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send a notification to a user.
        
        Args:
            user_id: User ID to send notification to
            title: Notification title
            message: Notification message
            severity: Severity level (info, warning, critical)
            metadata: Additional metadata to include
        """
        if self.db is None:
            logger.error("Cannot send notification: no database client")
            return
        
        try:
            notification_data = {
                "title": title,
                "message": message,
                "severity": severity,
                "created_at": datetime.now(timezone.utc),
                "read": False,
                "metadata": metadata or {},
            }
            
            # Store in user's notifications collection
            self.db.collection("users").document(user_id).collection(
                "notifications"
            ).add(notification_data)
            
            # Also update the user's notification counter
            user_ref = self.db.collection("users").document(user_id)
            user_ref.update({
                "unread_notifications": self.db.field_value.increment(1),
            })
            
            logger.info(
                f"Sent {severity} notification to user {user_id}: {title}"
            )
            
        except Exception as e:
            logger.error(f"Error sending notification: {e}", exc_info=True)
    
    async def send_daily_loss_alert(
        self,
        *,
        user_id: str,
        tenant_id: str,
        strategy_id: str,
        pnl_percentage: float,
        pnl_amount: float,
    ) -> None:
        """
        Send a daily loss limit alert notification.
        
        Args:
            user_id: User ID
            tenant_id: Tenant ID
            strategy_id: Strategy ID
            pnl_percentage: PnL percentage (-0.02 = -2%)
            pnl_amount: PnL amount in USD
        """
        await self.send_notification(
            user_id=user_id,
            title="🚨 Daily Loss Limit Breached",
            message=(
                f"Your strategy '{strategy_id}' has reached the daily loss limit "
                f"of -2% (current: {pnl_percentage*100:.2f}%, ${pnl_amount:.2f}). "
                f"All active strategies have been switched to SHADOW_MODE to protect your capital."
            ),
            severity="critical",
            metadata={
                "tenant_id": tenant_id,
                "strategy_id": strategy_id,
                "pnl_percentage": pnl_percentage,
                "pnl_amount": pnl_amount,
                "action_taken": "switched_to_shadow_mode",
            },
        )
    
    async def send_vix_guard_alert(
        self,
        *,
        user_id: str,
        vix_value: float,
        original_allocation: float,
        adjusted_allocation: float,
    ) -> None:
        """
        Send a VIX guard alert notification.
        
        Args:
            user_id: User ID
            vix_value: Current VIX value
            original_allocation: Original allocation amount
            adjusted_allocation: Adjusted allocation amount
        """
        await self.send_notification(
            user_id=user_id,
            title="⚠️ VIX Guard Activated",
            message=(
                f"Market volatility is elevated (VIX: {vix_value:.2f}). "
                f"Position sizing has been reduced by 50% to preserve capital "
                f"(${original_allocation:.2f} → ${adjusted_allocation:.2f})."
            ),
            severity="warning",
            metadata={
                "vix_value": vix_value,
                "original_allocation": original_allocation,
                "adjusted_allocation": adjusted_allocation,
                "reduction_percentage": 50,
            },
        )
    
    async def send_concentration_alert(
        self,
        *,
        user_id: str,
        ticker: str,
        concentration: float,
        ticker_value: float,
        portfolio_value: float,
    ) -> None:
        """
        Send a concentration limit alert notification.
        
        Args:
            user_id: User ID
            ticker: Stock ticker
            concentration: Current concentration (0.20 = 20%)
            ticker_value: Value of ticker position
            portfolio_value: Total portfolio value
        """
        await self.send_notification(
            user_id=user_id,
            title="⚠️ Concentration Limit Reached",
            message=(
                f"Position in {ticker} represents {concentration*100:.1f}% of your portfolio, "
                f"exceeding the 20% concentration limit. BUY signal has been downgraded to HOLD "
                f"to maintain portfolio diversification."
            ),
            severity="warning",
            metadata={
                "ticker": ticker,
                "concentration": concentration,
                "ticker_value": ticker_value,
                "portfolio_value": portfolio_value,
                "limit": 0.20,
            },
        )


def create_notification_service(db_client: Any = None) -> NotificationService:
    """
    Factory function to create a notification service.
    
    Args:
        db_client: Firestore client
    
    Returns:
        Configured NotificationService instance
    """
    return NotificationService(db_client=db_client)
