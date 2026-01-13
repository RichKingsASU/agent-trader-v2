"""
User Onboarding Cloud Function

Automatically provisions new users with default settings when they sign up.

This function:
1. Creates the user document under tenants/{tenantId}/users/{uid}
2. Provisions default secrets/keys structure
3. Sets up alpaca/snapshot paths
4. Initializes "Safe Mode" settings (trading disabled by default)

Triggered by Firebase Auth user creation.
"""

import logging
from typing import Any, Dict

import firebase_admin
from firebase_admin import firestore, auth as admin_auth
from firebase_functions import https_fn, identity_fn, options

logger = logging.getLogger(__name__)


def _get_firestore() -> firestore.Client:
    """Get Firestore client."""
    if not firebase_admin._apps:
        from functions.utils.firestore_guard import require_firestore_emulator_or_allow_prod
        require_firestore_emulator_or_allow_prod(caller="functions.user_onboarding._get_firestore")
        firebase_admin.initialize_app()
    return firestore.client()


@identity_fn.before_user_created()
def on_user_signup(event: identity_fn.AuthBlockingEvent) -> identity_fn.BeforeCreateResponse:
    """
    Provision new user with default settings.
    
    This blocking function runs BEFORE the user is created in Firebase Auth,
    allowing us to set custom claims and prepare the database.
    
    Flow:
    1. User signs up via Firebase Auth
    2. This function is triggered BEFORE user creation
    3. We assign a tenant_id (default or from invitation)
    4. Set custom claims on the user token
    5. User is created with tenant_id in their token
    6. on_user_created() triggers to provision Firestore documents
    
    Args:
        event: Auth blocking event with user data
        
    Returns:
        BeforeCreateResponse with custom claims
    """
    user_id = event.uid
    email = event.data.email or "unknown"
    
    logger.info(f"on_user_signup: Provisioning user {user_id} ({email})")
    
    try:
        # Determine tenant ID
        # For SaaS, you might:
        # 1. Read from invitation token/metadata
        # 2. Create a new tenant for each signup
        # 3. Assign to a default tenant
        
        # For now, assign to default tenant or create new one
        tenant_id = event.data.custom_claims.get("tenant_id") if event.data.custom_claims else None
        
        if not tenant_id:
            # Create new tenant for this user (single-tenant mode)
            # In multi-tenant mode, this would come from invitation/signup flow
            tenant_id = f"tenant_{user_id[:8]}"
            logger.info(f"Creating new tenant: {tenant_id}")
        
        # Set custom claims (tenant_id will be in user's ID token)
        return identity_fn.BeforeCreateResponse(
            custom_claims={
                "tenant_id": tenant_id,
                "role": "member",
                "onboarded_at": firestore.SERVER_TIMESTAMP,
            }
        )
        
    except Exception as e:
        logger.exception(f"Error in on_user_signup for user {user_id}: {e}")
        # Don't block user creation on errors
        return identity_fn.BeforeCreateResponse()


@identity_fn.on_user_created()
def on_user_created(event: identity_fn.UserRecord) -> None:
    """
    Complete user provisioning after user is created.
    
    This function runs AFTER the user is created in Firebase Auth.
    It provisions all necessary Firestore documents.
    
    Args:
        event: User record with uid, email, custom claims, etc.
    """
    user_id = event.uid
    email = event.email or "unknown"
    
    logger.info(f"on_user_created: Provisioning Firestore documents for user {user_id} ({email})")
    
    try:
        db = _get_firestore()
        
        # Extract tenant_id from custom claims
        tenant_id = event.custom_claims.get("tenant_id") if event.custom_claims else None
        
        if not tenant_id:
            # Fallback: create tenant if not set
            tenant_id = f"tenant_{user_id[:8]}"
            logger.warning(f"No tenant_id in custom claims, creating: {tenant_id}")
            
            # Set custom claims retroactively
            try:
                admin_auth.set_custom_user_claims(user_id, {"tenant_id": tenant_id, "role": "member"})
            except Exception as claim_error:
                logger.error(f"Failed to set custom claims: {claim_error}")
        
        # 1. Create tenant document (if it doesn't exist)
        tenant_ref = db.collection("tenants").document(tenant_id)
        tenant_doc = tenant_ref.get()
        
        if not tenant_doc.exists:
            tenant_ref.set({
                "name": f"Tenant {tenant_id}",
                "created_at": firestore.SERVER_TIMESTAMP,
                "owner_uid": user_id,
                "plan": "free",  # Default plan
                "status": "active",
            }, merge=True)
            logger.info(f"Created tenant document: {tenant_id}")
        
        # 2. Create membership document: tenants/{tenantId}/users/{uid}
        membership_ref = tenant_ref.collection("users").document(user_id)
        membership_ref.set({
            "role": "member",
            "email": email,
            "created_at": firestore.SERVER_TIMESTAMP,
            "onboarded": True,
        }, merge=True)
        logger.info(f"Created membership document: tenants/{tenant_id}/users/{user_id}")
        
        # 3. Create user root document: users/{uid}
        user_ref = db.collection("users").document(user_id)
        user_ref.set({
            "email": email,
            "tenant_id": tenant_id,
            "created_at": firestore.SERVER_TIMESTAMP,
            "onboarded": True,
        }, merge=True)
        logger.info(f"Created user root document: users/{user_id}")
        
        # 4. Provision secrets structure (empty by default)
        secrets_ref = user_ref.collection("secrets").document("alpaca")
        secrets_ref.set({
            "configured": False,
            "key_id": None,
            "secret_key": None,
            "base_url": "https://paper-api.alpaca.markets",  # Default to paper trading
            "created_at": firestore.SERVER_TIMESTAMP,
            "note": "Configure your Alpaca API keys in the Settings page",
        }, merge=True)
        logger.info(f"Created secrets document: users/{user_id}/secrets/alpaca")
        
        # 5. Initialize alpaca/snapshot path (empty snapshot)
        snapshot_ref = user_ref.collection("alpacaAccounts").document("snapshot")
        snapshot_ref.set({
            "configured": False,
            "equity": "0",
            "buying_power": "0",
            "cash": "0",
            "syncedAt": firestore.SERVER_TIMESTAMP,
            "note": "Connect your Alpaca account to see live data",
        }, merge=True)
        logger.info(f"Created account snapshot: users/{user_id}/alpacaAccounts/snapshot")
        
        # 6. Set Safe Mode (trading disabled by default)
        trading_status_ref = user_ref.collection("status").document("trading")
        trading_status_ref.set({
            "enabled": False,  # Safe Mode: disabled by default
            "mode": "safe",
            "reason": "New user onboarding - enable trading in Settings",
            "updated_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)
        logger.info(f"Created trading status (Safe Mode): users/{user_id}/status/trading")
        
        # 7. Create config document with defaults
        config_ref = user_ref.collection("config").document("preferences")
        config_ref.set({
            "theme": "dark",
            "notifications_enabled": True,
            "risk_tolerance": "moderate",
            "default_allocation": 0.1,  # 10% of buying power per trade
            "max_positions": 5,
            "created_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)
        logger.info(f"Created config document: users/{user_id}/config/preferences")
        
        # 8. Log onboarding completion to ops
        ops_ref = db.collection("ops").document("user_onboarding")
        ops_ref.set({
            "last_user_id": user_id,
            "last_user_email": email,
            "last_tenant_id": tenant_id,
            "timestamp": firestore.SERVER_TIMESTAMP,
        }, merge=True)
        
        logger.info(
            f"✅ User onboarding complete for {user_id} ({email}) "
            f"in tenant {tenant_id}"
        )
        
    except Exception as e:
        logger.exception(f"Error provisioning user {user_id}: {e}")
        
        # Store error for debugging
        try:
            db = _get_firestore()
            error_ref = db.collection("ops").document("onboarding_errors")
            error_ref.set({
                "last_error_user_id": user_id,
                "last_error_email": email,
                "error": str(e),
                "timestamp": firestore.SERVER_TIMESTAMP,
            }, merge=True)
        except Exception as nested_error:
            logger.error(f"Failed to log onboarding error: {nested_error}")


@https_fn.on_call(
    cors=options.CorsOptions(cors_origins="*", cors_methods=["POST"]),
)
def provision_user_manually(req: https_fn.CallableRequest) -> Dict[str, Any]:
    """
    Manually provision a user (for migration or admin purposes).
    
    This is a callable function for admins to provision users who signed up
    before the onboarding function was implemented.
    
    Args:
        req: Callable request with optional data:
            - user_id: User ID to provision (if not authenticated user)
            - tenant_id: Tenant ID to assign (optional)
    
    Returns:
        Dictionary with provisioning result
    """
    try:
        # Require authentication
        if not req.auth:
            raise https_fn.HttpsError(
                code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
                message="Authentication required",
            )
        
        # Get user ID (default to authenticated user)
        data = req.data or {}
        user_id = data.get("user_id", req.auth.uid)
        tenant_id = data.get("tenant_id")
        
        logger.info(f"Manual provisioning requested for user {user_id}")
        
        # Get user record
        user_record = admin_auth.get_user(user_id)
        
        # Create fake event for on_user_created
        class FakeEvent:
            def __init__(self, uid: str, email: str, custom_claims: Dict[str, Any]):
                self.uid = uid
                self.email = email
                self.custom_claims = custom_claims or {}
        
        # Set custom claims if tenant_id provided
        if tenant_id:
            admin_auth.set_custom_user_claims(user_id, {"tenant_id": tenant_id, "role": "member"})
            custom_claims = {"tenant_id": tenant_id, "role": "member"}
        else:
            custom_claims = user_record.custom_claims or {}
        
        # Call onboarding function
        event = FakeEvent(
            uid=user_id,
            email=user_record.email,
            custom_claims=custom_claims
        )
        on_user_created(event)
        
        return {
            "success": True,
            "user_id": user_id,
            "tenant_id": tenant_id or custom_claims.get("tenant_id"),
            "message": "User provisioned successfully",
        }
        
    except https_fn.HttpsError:
        raise
    except Exception as e:
        logger.exception(f"Error in manual provisioning: {e}")
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INTERNAL,
            message=f"Provisioning failed: {str(e)}",
        )
