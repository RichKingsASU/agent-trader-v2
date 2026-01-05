from __future__ import annotations

from typing import Any, Dict, Optional

import google.auth.transport.requests
from fastapi import Depends, HTTPException, Request, status
from google.oauth2 import id_token as google_id_token

from .config import Settings, get_settings


def _extract_bearer_token(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts[0].strip().lower(), parts[1].strip()
    if scheme != "bearer" or not token:
        return None
    return token


def _verify_google_id_token(
    token: str,
    audiences: list[str],
) -> Dict[str, Any]:
    """
    Verify a Google-issued OIDC token (e.g., Cloud Run IAM).

    If audiences are provided, accept any of them.
    """
    req = google.auth.transport.requests.Request()

    if audiences:
        last_err: Optional[Exception] = None
        for aud in audiences:
            try:
                return google_id_token.verify_oauth2_token(token, req, audience=aud)
            except Exception as e:  # noqa: BLE001 - surface as auth failure below
                last_err = e
        raise last_err or ValueError("Token verification failed")

    # Audience not enforced (use with caution). Still validates signature/issuer.
    return google_id_token.verify_oauth2_token(token, req, audience=None)


def require_gcp_identity(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    """
    FastAPI dependency enforcing Cloud Run IAM authentication.
    """
    if settings.AUTH_DISABLED:
        return {"sub": "local", "email": "local@example.com"}

    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization: Bearer token",
        )

    try:
        claims = _verify_google_id_token(token, settings.AUTH_AUDIENCES)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid ID token: {e}",
        ) from e

    if settings.AUTH_ALLOWED_EMAILS:
        email = claims.get("email")
        if not email or email not in set(settings.AUTH_ALLOWED_EMAILS):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Caller email is not allowed",
            )

    return claims

