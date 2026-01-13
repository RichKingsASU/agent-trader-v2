from __future__ import annotations

import os
import threading
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore
import google.auth


_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def _is_emulator_mode() -> bool:
    """
    Best-effort detection of local Firebase/Firestore emulator usage.

    We treat emulator mode as a special case where credentials are *not required*.
    - Firestore emulator: FIRESTORE_EMULATOR_HOST
    - Auth emulator: FIREBASE_AUTH_EMULATOR_HOST
    - Realtime DB emulator: FIREBASE_DATABASE_EMULATOR_HOST
    """
    for k in ("FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST", "FIREBASE_DATABASE_EMULATOR_HOST"):
        if (os.getenv(k) or "").strip():
            return True
    return False


def _resolve_project_id(explicit_project_id: Optional[str] = None) -> Optional[str]:
    if explicit_project_id:
        return explicit_project_id

    env_project_id = (
        os.getenv("FIREBASE_PROJECT_ID")
        # Back-compat: older env name used in this repo
        or os.getenv("FIRESTORE_PROJECT_ID")
        # Alternate names commonly used by gcloud / CI
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
    )
    if env_project_id:
        return env_project_id

    return None


_init_lock = threading.Lock()


def init_firebase_admin(*, project_id: Optional[str] = None) -> None:
    """
    Initialize Firebase Admin SDK exactly once.

    Behavior:
    - In production: uses Application Default Credentials (ADC).
    - In emulator mode: uses anonymous credentials (no ADC required).

    Supported env:
    - GOOGLE_APPLICATION_CREDENTIALS (ADC on local machines/CI)
    - FIREBASE_PROJECT_ID (preferred) / FIRESTORE_PROJECT_ID (back-compat)
    - FIRESTORE_EMULATOR_HOST / FIREBASE_AUTH_EMULATOR_HOST (emulator mode)
    """
    if firebase_admin._apps:
        return

    with _init_lock:
        if firebase_admin._apps:
            return

        resolved_project_id = _resolve_project_id(project_id)

        emulator_mode = _is_emulator_mode()
        if emulator_mode:
            # In emulator mode, Firestore/Auth emulators don't require credentials.
            # We still set a project id to keep resource paths stable.
            if not resolved_project_id:
                resolved_project_id = "demo-agenttrader-local"
            anon_cls = getattr(credentials, "AnonymousCredentials", None)
            if anon_cls is None:
                raise RuntimeError(
                    "Emulator mode detected but firebase_admin.credentials.AnonymousCredentials is unavailable. "
                    "Upgrade firebase-admin or run with ADC."
                )
            cred = anon_cls()
        else:
            try:
                cred = credentials.ApplicationDefault()
            except Exception as e:
                # Fail fast: ADC must be available outside emulator mode.
                raise RuntimeError(
                    "Failed to load Application Default Credentials (ADC) for Firebase Admin SDK. "
                    "Locally: run `gcloud auth application-default login` (or set GOOGLE_APPLICATION_CREDENTIALS). "
                    "In production: run on Cloud Run/GCE with a service account that has Firestore permissions."
                ) from e

            if not resolved_project_id:
                # Ask ADC for the active project id (common on Cloud Run / GCE).
                try:
                    # Explicitly request cloud-platform scope to avoid "Missing scope" errors
                    # in environments where ADC needs scopes specified at construction time.
                    _, resolved_project_id = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
                except Exception:
                    resolved_project_id = None

        if not resolved_project_id:
            raise RuntimeError(
                "Firebase project id could not be resolved. Set FIREBASE_PROJECT_ID "
                "(or ensure your ADC environment provides a project id)."
            )

        try:
            firebase_admin.initialize_app(cred, {"projectId": resolved_project_id})
        except Exception as e:
            raise RuntimeError(
                "Failed to initialize Firebase Admin SDK with Application Default Credentials (ADC). "
                "Locally: run `gcloud auth application-default login`. "
                "In production: run on Cloud Run/GCE with a service account that has Firestore permissions."
            ) from e


def get_firestore_client(*, project_id: Optional[str] = None):
    init_firebase_admin(project_id=project_id)
    return firestore.client()

