#!/usr/bin/env python3
"""
Initialize Shadow Mode Configuration in Firestore

This script creates/updates the systemStatus/config document with
the is_shadow_mode flag, defaulting to True for safety.

Usage:
    python scripts/init_shadow_mode_config.py

Environment Variables:
    - FIREBASE_PROJECT_ID or GOOGLE_CLOUD_PROJECT
    - GOOGLE_APPLICATION_CREDENTIALS (path to service account key)

For local development:
    gcloud auth application-default login
    export FIREBASE_PROJECT_ID=your-project-id
    python scripts/init_shadow_mode_config.py
"""

from datetime import datetime, timezone
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import scripts.lib.exec_guard as exec_guard

from backend.persistence.firebase_client import get_firestore_client
from google.cloud import firestore


def init_shadow_mode_config():
    """
    Initialize the systemStatus/config document with shadow mode configuration.
    
    Sets is_shadow_mode to True by default for safety.
    """
    try:
        print("Initializing Shadow Mode configuration...")
        
        # Get Firestore client
        db = get_firestore_client()
        
        # Reference to systemStatus/config document
        config_ref = db.collection("systemStatus").document("config")
        
        # Check if document exists
        doc = config_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            current_shadow_mode = data.get("is_shadow_mode")
            
            if current_shadow_mode is not None:
                print(f"✓ Shadow mode already configured: is_shadow_mode = {current_shadow_mode}")
                print(f"  Last updated: {data.get('updated_at', 'N/A')}")
                
                # Ask if user wants to update
                response = input("\nDo you want to update the configuration? (y/N): ")
                if response.lower() != 'y':
                    print("Configuration unchanged.")
                    return
            else:
                print("Document exists but is_shadow_mode field is missing. Adding it...")
        else:
            print("systemStatus/config document does not exist. Creating it...")
        
        # Prepare configuration data
        config_data = {
            "is_shadow_mode": True,  # Default to True for safety
            "updated_at": firestore.SERVER_TIMESTAMP,
            "initialized_by": "init_shadow_mode_config.py",
            "description": "Shadow mode controls whether trades are simulated (True) or executed live (False)",
        }
        
        # Write to Firestore (merge to preserve other fields)
        config_ref.set(config_data, merge=True)
        
        print("\n✓ Successfully initialized Shadow Mode configuration:")
        print(f"  is_shadow_mode: True")
        print(f"  Document: systemStatus/config")
        print(f"\n⚠️  Shadow Mode is now ENABLED (default for safety)")
        print("   All trades will be simulated and logged to shadowTradeHistory.")
        print("   To disable shadow mode, use the UI toggle or update Firestore manually.")
        
    except Exception as e:
        print(f"\n✗ Error initializing shadow mode configuration: {e}")
        sys.exit(1)


def display_current_config():
    """Display the current shadow mode configuration."""
    try:
        db = get_firestore_client()
        config_ref = db.collection("systemStatus").document("config")
        doc = config_ref.get()
        
        print("\n" + "="*60)
        print("CURRENT SHADOW MODE CONFIGURATION")
        print("="*60)
        
        if doc.exists:
            data = doc.to_dict()
            is_shadow = data.get("is_shadow_mode", "NOT SET")
            updated_at = data.get("updated_at", "N/A")
            
            print(f"is_shadow_mode: {is_shadow}")
            print(f"Updated at: {updated_at}")
            print(f"Description: {data.get('description', 'N/A')}")
            
            if is_shadow:
                print("\n✓ Shadow Mode is ENABLED (SAFE)")
                print("  All trades are simulated. No broker contact.")
            else:
                print("\n⚠️  Shadow Mode is DISABLED (LIVE)")
                print("  Trades will be submitted to the broker.")
        else:
            print("Configuration document does not exist.")
            print("Run this script to initialize it.")
        
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"Error reading configuration: {e}")


if __name__ == "__main__":
    exec_guard.enforce_execution_policy(__file__, sys.argv)
    print("Shadow Mode Configuration Initializer")
    print("=" * 60)
    
    # First, display current configuration
    try:
        display_current_config()
    except Exception:
        print("Could not read current configuration.\n")
    
    # Initialize/update configuration
    init_shadow_mode_config()
    
    # Display final configuration
    display_current_config()
