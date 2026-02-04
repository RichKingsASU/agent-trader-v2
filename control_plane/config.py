"""
Configuration for the Operator Control Plane.

All settings are loaded from environment variables.
NO SECRETS ARE STORED IN CODE.
"""

import os
from typing import List

# --- Google OAuth Configuration ---
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")

# Operator email allowlist (comma-separated)
OPERATOR_EMAILS_RAW = os.environ.get("OPERATOR_EMAILS", "")
OPERATOR_EMAILS: List[str] = [
    email.strip() for email in OPERATOR_EMAILS_RAW.split(",") if email.strip()
]

# --- Trading Safety Configuration ---
# These are READ from environment, never written by this service
TRADING_MODE = os.environ.get("TRADING_MODE", "shadow")
OPTIONS_EXECUTION_MODE = os.environ.get("OPTIONS_EXECUTION_MODE", "shadow")
EXECUTION_ENABLED = os.environ.get("EXECUTION_ENABLED", "0") == "1"
EXECUTION_HALTED = os.environ.get("EXECUTION_HALTED", "0") == "1"
EXEC_GUARD_UNLOCK = os.environ.get("EXEC_GUARD_UNLOCK", "0") == "1"
EXECUTION_CONFIRM_TOKEN = os.environ.get("EXECUTION_CONFIRM_TOKEN", "")

# Alpaca configuration (for validation only - never used directly)
APCA_API_BASE_URL = os.environ.get("APCA_API_BASE_URL", "")
PAPER_API_URL = "https://paper-api.alpaca.markets"

# --- Application Configuration ---
APP_NAME = "Operator Control Plane"
APP_VERSION = "1.0.0"
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")

# Session secret for OAuth
SESSION_SECRET = os.environ.get("SESSION_SECRET", "CHANGE_ME_IN_PRODUCTION")

# --- Firestore Configuration ---
# Used for reading intent history only
FIRESTORE_PROJECT_ID = os.environ.get("FIRESTORE_PROJECT_ID", "")


def validate_config() -> List[str]:
    """
    Validate critical configuration.
    Returns list of error messages (empty if valid).
    """
    errors = []
    
    if not GOOGLE_CLIENT_ID:
        errors.append("GOOGLE_CLIENT_ID not set")
    
    if not GOOGLE_CLIENT_SECRET:
        errors.append("GOOGLE_CLIENT_SECRET not set")
    
    if not OPERATOR_EMAILS:
        errors.append("OPERATOR_EMAILS not set (no operators allowed)")
    
    if SESSION_SECRET == "CHANGE_ME_IN_PRODUCTION":
        errors.append("SESSION_SECRET must be changed in production")
    
    return errors


def get_system_status() -> dict:
    """
    Get current system status from environment variables.
    This is READ-ONLY - never modifies environment.
    """
    return {
        "trading_mode": TRADING_MODE,
        "options_execution_mode": OPTIONS_EXECUTION_MODE,
        "execution_enabled": EXECUTION_ENABLED,
        "execution_halted": EXECUTION_HALTED,
        "exec_guard_locked": not EXEC_GUARD_UNLOCK,
        "apca_url_is_paper": APCA_API_BASE_URL.rstrip("/v2").rstrip("/") == PAPER_API_URL,
    }


def is_execution_allowed() -> tuple[bool, str]:
    """
    Check if execution is allowed based on ALL safety invariants.
    Returns (allowed, reason).
    """
    status = get_system_status()
    
    if status["execution_halted"]:
        return False, "Execution is halted (EXECUTION_HALTED=1)"
    
    if status["trading_mode"] != "paper":
        return False, f"TRADING_MODE must be 'paper', got '{status['trading_mode']}'"
    
    if status["options_execution_mode"] != "paper":
        return False, f"OPTIONS_EXECUTION_MODE must be 'paper', got '{status['options_execution_mode']}'"
    
    if not status["execution_enabled"]:
        return False, "EXECUTION_ENABLED is not set to 1"
    
    if status["exec_guard_locked"]:
        return False, "EXEC_GUARD_UNLOCK is not set to 1"
    
    if not EXECUTION_CONFIRM_TOKEN:
        return False, "EXECUTION_CONFIRM_TOKEN is not set"
    
    if not status["apca_url_is_paper"]:
        return False, f"APCA_API_BASE_URL must be paper API, got '{APCA_API_BASE_URL}'"
    
    return True, "All safety invariants satisfied"
