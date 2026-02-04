"""
Google OAuth authentication middleware for the Operator Control Plane.

Only allows access to operators on the email allowlist.
"""

import os
from typing import Optional
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware

from control_plane.config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    OPERATOR_EMAILS,
    SESSION_SECRET,
)

# Configure OAuth
oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def get_current_user_email(request: Request) -> Optional[str]:
    """Get the currently authenticated user's email from session."""
    return request.session.get("user_email")


def is_operator_authorized(email: str) -> bool:
    """Check if email is in the operator allowlist."""
    return email in OPERATOR_EMAILS


async def require_auth(request: Request) -> str:
    """
    Require authentication and authorization.
    Returns the authenticated user's email.
    Raises HTTPException if not authenticated or not authorized.
    """
    email = get_current_user_email(request)
    
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
        )
    
    if not is_operator_authorized(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Email {email} is not authorized as an operator.",
        )
    
    return email


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce authentication on all /api/* routes.
    Public routes: /auth/*, /health
    """
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        
        # Allow public routes
        if path.startswith("/auth/") or path == "/health":
            return await call_next(request)
        
        # Enforce auth for all other routes
        try:
            await require_auth(request)
        except HTTPException as e:
            # For API routes, return 401 so the frontend can handle it
            if path.startswith("/api/"):
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": e.detail},
                )
            # For page routes (like root), redirect to login
            return RedirectResponse(url="/auth/login", status_code=302)
        
        return await call_next(request)
