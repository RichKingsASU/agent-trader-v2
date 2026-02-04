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

from control_plane.config import (
    APP_NAME,
    APP_VERSION,
    CORS_ORIGINS,
    SESSION_SECRET,
    validate_config,
)
from control_plane.auth import AuthMiddleware, oauth
from control_plane.routes import status, intent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


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

# Add session middleware (required for OAuth)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=3600,  # 1 hour
    same_site="lax",
    https_only=True,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Add authentication middleware
app.add_middleware(AuthMiddleware)

# Include routers
app.include_router(status.router, prefix="/api", tags=["status"])
app.include_router(intent.router, prefix="/api", tags=["intent"])


# --- Authentication Routes ---

@app.get("/auth/login")
async def login(request: Request):
    """Initiate Google OAuth login flow."""
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle Google OAuth callback."""
    try:
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
        return JSONResponse(
            status_code=500,
            content={"error": "Authentication failed"},
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
    """Root endpoint."""
    return {
        "service": APP_NAME,
        "version": APP_VERSION,
        "message": "Operator Control Plane - Paper Trading Only",
        "auth_required": True,
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
