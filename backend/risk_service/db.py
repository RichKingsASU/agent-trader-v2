from __future__ import annotations

from backend.persistence.firebase_client import get_firestore_client


def get_db():
    """
    Returns a Firestore client.

    Env contract:
    - GOOGLE_APPLICATION_CREDENTIALS (or ADC on GCP)
    - FIREBASE_PROJECT_ID
    """
    return get_firestore_client()
