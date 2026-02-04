"""
FastAPI application for the Operator Control Plane.

This is a minimal, secure backend for supervised paper options trading.
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from control_plane.config import (
    APP_NAME,
    APP_VERSION,
    CORS_ORIGINS,
    SESSION_SECRET,
    GOOGLE_REDIRECT_URI,
    validate_config,
)
from control_plane.auth import AuthMiddleware, oauth
from control_plane.routes import status, intent, account

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ProxyHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to respect X-Forwarded-Proto from load balancers (Cloud Run).
    Ensures that request.url_for generates https:// URLs.
    """
    async def dispatch(self, request: Request, call_next):
        # Respect X-Forwarded-Proto from Cloud Run load balancer
        proto = request.headers.get("x-forwarded-proto")
        if proto:
            request.scope["scheme"] = proto
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events."""
    # Startup
    logger.info(f"Starting {APP_NAME} v{APP_VERSION}")
    
    # Validate configuration
    config_errors = validate_config()
    if config_errors:
        logger.error("Configuration errors detected:")
        for error in config_errors:
            logger.error(f"  - {error}")
        logger.warning("Service starting with configuration issues - some features may not work")
    else:
        logger.info("Configuration validated successfully")
    
    yield
    
    # Shutdown
    logger.info(f"Shutting down {APP_NAME}")


# Create FastAPI application
app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Minimal, secure backend for supervised paper options trading",
    lifespan=lifespan,
)

# Include routers
app.include_router(status.router, prefix="/api", tags=["status"])
app.include_router(intent.router, prefix="/api", tags=["intent"])
app.include_router(account.router, prefix="/api", tags=["account"])

# ═══════════════════════════════════════════════════════════════════════════════
# MIDDLEWARE STACK (ORDER MATTERS)
# Outermost handlers run FIRST for requests and LAST for responses.
# ═══════════════════════════════════════════════════════════════════════════════

# 3. Authentication logic
app.add_middleware(AuthMiddleware)

# 2. CORS (Pre-flight checks)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# 1. Sessions (Must see HTTPS scheme to set Secure cookies)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=900,  # 15 minutes
    same_site="lax",
    https_only=True,
)

# 0. Proxy Headers (Fixes request.scope['scheme'] for outermost layers)
app.add_middleware(ProxyHeadersMiddleware)



# --- Authentication Routes ---

@app.get("/auth/login")
async def login(request: Request):
    """Initiate Google OAuth login flow."""
    # Use the configured redirect URI if available, otherwise fall back to dynamic lookup
    # This ensures HTTPS is used even when behind a proxy
    redirect_uri = GOOGLE_REDIRECT_URI or request.url_for("auth_callback")
    logger.info(f"Initiating login with redirect_uri: {redirect_uri}")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle Google OAuth callback."""
    try:
        # authlib automatically uses the redirect_uri from the OAuth state
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")
        
        if not user_info:
            return JSONResponse(
                status_code=400,
                content={"error": "Failed to get user info from Google"},
            )
        
        email = user_info.get("email")
        if not email:
            return JSONResponse(
                status_code=400,
                content={"error": "No email in user info"},
            )
        
        # Store email in session
        request.session["user_email"] = email
        request.session["user_name"] = user_info.get("name", "")
        
        logger.info(f"User logged in: {email}")
        
        # Redirect to UI (or API status page)
        return RedirectResponse(url="/api/status")
        
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        # Log specific details for debugging mismatching_state
        logger.error(f"Request URL: {request.url}")
        logger.error(f"Headers: {dict(request.headers)}")
        logger.error(f"Session data: {request.session}")

        return JSONResponse(
            status_code=500,
            content={"error": "Authentication failed", "detail": str(e)},
        )


@app.get("/auth/logout")
async def logout(request: Request):
    """Log out the current user."""
    email = request.session.get("user_email")
    request.session.clear()
    logger.info(f"User logged out: {email}")
    return JSONResponse(content={"message": "Logged out successfully"})


# --- Health Check ---

@app.get("/health")
async def health_check():
    """Health check endpoint (no auth required)."""
    return {"status": "healthy", "service": APP_NAME, "version": APP_VERSION}


# --- Root ---

@app.get("/")
async def root():
    """Serve the frontend SPA root."""
    # Check if frontend exists (frontend_dist defined later, but simplistic check here or import)
    # Re-resolving path here to be safe given local scope order
    dist_path = os.path.join(os.path.dirname(__file__), "frontend/dist")
    if os.path.exists(os.path.join(dist_path, "index.html")):
        return FileResponse(os.path.join(dist_path, "index.html"))
    
    return {
        "service": APP_NAME,
        "version": APP_VERSION,
        "message": "Operator Control Plane - API Mode (Frontend not found)",
    }


# --- Static Files (Frontend) ---

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Mount static files (assets, js, css) if they exist
# This is for the built React app in /app/control_plane/frontend/dist
frontend_dist = os.path.join(os.path.dirname(__file__), "frontend/dist")

if os.path.isdir(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Serve the frontend SPA for any non-API routes."""
        # API routes are already handled above due to precedence
        
        # Check if file exists in dist (e.g. favicon.ico)
        file_path = os.path.join(frontend_dist, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
            
        # Fallback to index.html for SPA routing
        return FileResponse(os.path.join(frontend_dist, "index.html"))

else:
    logger.warning(f"Frontend dist not found at {frontend_dist}. Running in API-only mode.")

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "control_plane.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        reload=True,
    )
