from __future__ import annotations

import logging
from fastapi import Depends, HTTPException, Request, status
from firebase_admin import auth as firebase_auth

from backend.persistence.firebase_client import init_firebase_admin, get_firestore_client
from backend.common.logging import log_event

from .context import TenantContext

logger = logging.getLogger(__name__)


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization") or ""
    if not header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization: Bearer <token>",
        )
    token = header.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Empty bearer token")
    return token


def get_tenant_context(request: Request) -> TenantContext:
    """
    Verify Firebase ID token and extract (uid, tenant_id).

    Tenant id is read from Firebase custom claims:
      - tenant_id (preferred)
      - tenantId (back-compat)
    """
    init_firebase_admin()
    # Never log the token value (PII/credential). Only log presence/metadata.
    try:
        token_present = bool((request.headers.get("Authorization") or "").strip())
    except Exception:
        token_present = False

    token = _bearer_token(request)

    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception as e:
        try:
            log_event(
                logger,
                "auth_failure",
                severity="WARNING",
                auth_provider="firebase",
                reason="verify_id_token_failed",
                authorization_present=bool(token_present),
                error=f"{type(e).__name__}: {e}",
            )
        except Exception:
            pass
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid ID token: {e}")

    uid = str(decoded.get("uid") or decoded.get("sub") or "").strip()
    if not uid:
        try:
            log_event(
                logger,
                "auth_failure",
                severity="WARNING",
                auth_provider="firebase",
                reason="missing_uid",
            )
        except Exception:
            pass
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ID token: missing uid")

    tenant_id = str(decoded.get("tenant_id") or decoded.get("tenantId") or "").strip()
    if not tenant_id:
        try:
            log_event(
                logger,
                "auth_failure",
                severity="WARNING",
                auth_provider="firebase",
                reason="missing_tenant_id_claim",
                uid=uid,
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing tenant_id claim on Firebase Auth token",
        )

    # Defense in depth: require membership doc to exist.
    db = get_firestore_client()
    member_ref = db.document(f"tenants/{tenant_id}/users/{uid}")
    if not member_ref.get().exists:
        try:
            log_event(
                logger,
                "auth_failure",
                severity="WARNING",
                auth_provider="firebase",
                reason="not_tenant_member",
                uid=uid,
                tenant_id=tenant_id,
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of this tenant",
        )

    try:
        log_event(
            logger,
            "auth_success",
            severity="INFO",
            auth_provider="firebase",
            uid=uid,
            tenant_id=tenant_id,
        )
    except Exception:
        pass
    return TenantContext(uid=uid, tenant_id=tenant_id, claims=decoded)


TenantDep = Depends(get_tenant_context)

