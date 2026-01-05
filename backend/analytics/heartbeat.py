"""
Heartbeat monitoring for system health checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Literal, Optional

from google.cloud import firestore

from backend.persistence.firebase_client import get_db


HeartbeatStatus = Literal["healthy", "degraded", "down", "unknown"]


@dataclass
class HeartbeatInfo:
    """Heartbeat information for a service"""
    
    service_id: str
    last_heartbeat: Optional[datetime]
    status: HeartbeatStatus
    seconds_since_heartbeat: Optional[float]
    is_stale: bool


def check_heartbeat(
    tenant_id: str,
    service_id: str,
    stale_threshold_seconds: int = 120,
) -> HeartbeatInfo:
    """
    Check the heartbeat status for a service.
    
    Args:
        tenant_id: Tenant ID to check
        service_id: Service identifier (e.g., "market_ingest", "execution_engine")
        stale_threshold_seconds: Seconds before heartbeat is considered stale
        
    Returns:
        HeartbeatInfo object with status and timing information
    """
    db = get_db()
    
    try:
        # Check tenant-scoped heartbeat
        doc_ref = db.collection("tenants").document(tenant_id).collection("ops_heartbeats").document(service_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            return HeartbeatInfo(
                service_id=service_id,
                last_heartbeat=None,
                status="unknown",
                seconds_since_heartbeat=None,
                is_stale=True,
            )
        
        data = doc.to_dict()
        last_heartbeat_raw = data.get("last_heartbeat") or data.get("last_heartbeat_at")
        
        if not last_heartbeat_raw:
            return HeartbeatInfo(
                service_id=service_id,
                last_heartbeat=None,
                status="unknown",
                seconds_since_heartbeat=None,
                is_stale=True,
            )
        
        # Parse timestamp
        if isinstance(last_heartbeat_raw, datetime):
            last_heartbeat = last_heartbeat_raw
        else:
            # Firestore timestamp
            last_heartbeat = last_heartbeat_raw.to_datetime() if hasattr(last_heartbeat_raw, 'to_datetime') else datetime.now(timezone.utc)
        
        # Calculate staleness
        now = datetime.now(timezone.utc)
        last_heartbeat = last_heartbeat.replace(tzinfo=timezone.utc) if last_heartbeat.tzinfo is None else last_heartbeat
        delta = now - last_heartbeat
        seconds_since = delta.total_seconds()
        
        is_stale = seconds_since > stale_threshold_seconds
        
        # Determine status
        status_field = data.get("status", "unknown").lower()
        
        if is_stale:
            status = "down"
        elif status_field in ["running", "healthy", "ok"]:
            status = "healthy"
        elif status_field in ["degraded", "warning"]:
            status = "degraded"
        elif status_field in ["error", "down", "stopped"]:
            status = "down"
        else:
            status = "unknown"
        
        return HeartbeatInfo(
            service_id=service_id,
            last_heartbeat=last_heartbeat,
            status=status,
            seconds_since_heartbeat=seconds_since,
            is_stale=is_stale,
        )
        
    except Exception as e:
        # Log error but don't crash
        print(f"Error checking heartbeat for {service_id}: {e}")
        return HeartbeatInfo(
            service_id=service_id,
            last_heartbeat=None,
            status="unknown",
            seconds_since_heartbeat=None,
            is_stale=True,
        )


def write_heartbeat(
    tenant_id: str,
    service_id: str,
    status: str = "running",
    metadata: Optional[dict] = None,
) -> None:
    """
    Write a heartbeat for a service.
    
    Args:
        tenant_id: Tenant ID
        service_id: Service identifier
        status: Status string (e.g., "running", "degraded", "stopped")
        metadata: Optional additional metadata to store
    """
    db = get_db()
    
    doc_data = {
        "last_heartbeat": firestore.SERVER_TIMESTAMP,
        "status": status,
        "service_id": service_id,
    }
    
    if metadata:
        doc_data.update(metadata)
    
    doc_ref = db.collection("tenants").document(tenant_id).collection("ops_heartbeats").document(service_id)
    doc_ref.set(doc_data, merge=True)
